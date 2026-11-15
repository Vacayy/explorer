"""Synthetic SQLite → PostgreSQL read-contract comparison; no live services."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from models.spine import FeedDocument, FeedResponse

try:
    import psycopg
except ImportError:
    psycopg = None

from pipeline.postgres_document_read import PostgreSQLDocumentReader
from routers import spine_doc, spine_feed
import tests.test_document_read_boundary as detail_fixtures


def sqlite_feed(**overrides):
    args = dict(q=None, source=None, stock=None, industry=None, topic=None,
                page=1, size=20, days=None, sort='relevance')
    args.update(overrides)
    return spine_feed.get_feed(**args)


@unittest.skipUnless(psycopg and os.getenv('REFACTOR_POSTGRES_DSN') and
                     os.getenv('REFACTOR_TEST_DISPOSABLE') == '1',
                     'disposable isolated PostgreSQL fixture not configured')
class PostgreSQLDocumentReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        target = psycopg.conninfo.conninfo_to_dict(cls.dsn)
        if (target.get('host'), target.get('dbname'), target.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing to run fixture outside the isolated test database')
        cls.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(cls.schema)))
        with cls.connect() as conn:
            ddl = Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql'
            conn.execute(ddl.read_text())
        fixture = detail_fixtures.DocumentReadBoundaryTests('test_detail_keeps_original_summary_attachment_and_entity')
        fixture.setUp()
        try:
            cls.original = [spine_doc.get_document(i) for i in (1, 2)]
            with patch.object(spine_feed, 'get_connection', side_effect=fixture.connect), \
                 patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
                cls.original_feed = sqlite_feed()
                cls.original_blog = sqlite_feed(source='note')
        finally:
            fixture.tearDown()
        with cls.connect() as conn:
            for doc in cls.original:
                payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
                conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb)',
                             (doc.id, doc.source_type, doc.published_at or None, payload))
            for ordinal, doc in enumerate(cls.original_feed.items):
                payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
                conn.execute('INSERT INTO document_list_projection VALUES (%s,%s,%s::jsonb)',
                             (ordinal, doc.id, payload))
        cls.reader = PostgreSQLDocumentReader(cls.connect)

    @classmethod
    def connect(cls):
        return psycopg.connect(cls.dsn, options=f'-c search_path={cls.schema}')

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(cls.schema)))

    def test_detail_matches_existing_sqlite_response_and_missing(self):
        for expected in self.original:
            self.assertEqual(self.reader.get(expected.id).model_dump(), expected.model_dump())
        self.assertIsNone(self.reader.get(999))

    def test_list_preserves_sqlite_rows_summary_and_pagination(self):
        expected = self.original_feed
        self.assertEqual(expected.total, 2)
        self.assertEqual(len(expected.items), 3)  # Existing join includes both enrichments.
        actual = self.reader.list()
        self.assertEqual(actual.total, expected.total)
        self.assertEqual([d.model_dump() for d in actual.items], [d.model_dump() for d in expected.items])
        pages = [self.reader.list(page=i, size=1).items for i in (1, 2, 3)]
        self.assertEqual([d.model_dump() for page in pages for d in page],
                         [d.model_dump() for d in expected.items])
        filtered = self.reader.list(source='note')
        self.assertEqual([d.model_dump() for d in filtered.items],
                         [d.model_dump() for d in self.original_blog.items])
        self.assertEqual(filtered.total, self.original_blog.total)
        self.assertEqual(self.reader.list(source='missing').items, [])
        for kwargs in ({'page': 0}, {'size': 0}, {'size': 101}):
            with self.assertRaises(ValueError):
                self.reader.list(**kwargs)

    def test_synthetic_http_contract_and_attachment(self):
        app = FastAPI()
        reader = self.reader

        @app.get('/api/spine/doc/{doc_id}', response_model=FeedDocument)
        def detail(doc_id: int):
            doc = reader.get(doc_id)
            if doc is None:
                raise HTTPException(404, '문서를 찾을 수 없습니다')
            return doc

        @app.get('/api/spine/feed', response_model=FeedResponse)
        def feed(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
            return reader.list(page=page, size=size)

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / 'media'
            (media / 'fixtures').mkdir(parents=True)
            image = b'\xff\xd8\xff synthetic attachment'
            (media / 'fixtures/example.jpg').write_bytes(image)
            (Path(tmp) / 'private.txt').write_text('private synthetic fixture')
            app.mount('/media', StaticFiles(directory=media))
            client = TestClient(app)
            self.assertEqual(client.get('/api/spine/doc/1').json(), self.original[0].model_dump(mode='json'))
            self.assertEqual(client.get('/api/spine/doc/999').status_code, 404)
            response = client.get('/api/spine/feed?size=1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'][0], self.original_feed.items[0].model_dump(mode='json'))
            self.assertEqual(client.get('/api/spine/feed?size=0').status_code, 422)
            self.assertEqual(client.post('/api/spine/doc/1').status_code, 405)
            self.assertEqual(client.get('/media/fixtures/example.jpg').content, image)
            self.assertEqual(client.get('/media/%2e%2e/private.txt').status_code, 404)

    def test_projection_rejects_mismatched_identity(self):
        payload = json.dumps(self.original[0].model_dump(mode='json'))
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connect() as conn:
                conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb)',
                             (42, 'blog', None, payload))


if __name__ == '__main__':
    unittest.main()

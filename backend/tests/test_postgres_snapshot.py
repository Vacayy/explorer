"""Synthetic snapshot replacement and rollback in a disposable PostgreSQL DB."""
import os
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

try:
    import psycopg
except ImportError:
    psycopg = None

from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_snapshot import load_snapshot
import tests.test_document_read_boundary as detail_fixtures


@unittest.skipUnless(psycopg and os.getenv('REFACTOR_POSTGRES_DSN') and
                     os.getenv('REFACTOR_TEST_DISPOSABLE') == '1',
                     'disposable isolated PostgreSQL fixture not configured')
class SnapshotReplacementTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        target = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (target.get('host'), target.get('dbname'), target.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(self.schema)))
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        self.fixture = detail_fixtures.DocumentReadBoundaryTests('test_raw_fallback_and_missing')
        self.fixture.setUp()
        self.reader = PostgreSQLDocumentReader(self.pg)

    def tearDown(self):
        self.fixture.tearDown()
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(self.schema)))

    def pg(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def load(self, at):
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
                return load_snapshot(source, self.pg, snapshot_at=at)
        finally:
            source.close()

    def test_replacement_idempotency_and_failure_rollback(self):
        first_at = '2026-01-03T00:00:00+00:00'
        second_at = '2026-01-04T00:00:00+00:00'
        result = self.load(first_at)
        self.assertEqual((result['documents'], result['list_rows']), (2, 3))
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.list().total, 2)
        self.assertEqual(len(self.reader.list().items), 3)
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], first_at)

        with self.fixture.connect() as c:
            c.execute("UPDATE raw_documents SET markdown='수정 원문',media_json='[\"fixtures/new.jpg\"]' WHERE id=1")
            c.execute('DELETE FROM raw_documents WHERE id=2')
            c.execute("INSERT INTO raw_documents VALUES(3,'note','n3','새 문서',NULL,'2026-01-05','새 원문',NULL,NULL,NULL)")
        self.load(second_at)
        self.assertIsNone(self.reader.get(2))
        self.assertEqual(self.reader.get(1).images, ['fixtures/new.jpg'])
        self.assertEqual(self.reader.get(3).content, '새 원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], second_at)
        before = [x.model_dump() for x in self.reader.list().items]
        self.load(second_at)
        self.assertEqual([x.model_dump() for x in self.reader.list().items], before)

        with self.pg() as c:
            c.execute("CREATE FUNCTION fail_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
            c.execute('CREATE TRIGGER fail_fixture BEFORE INSERT ON document_projection FOR EACH ROW EXECUTE FUNCTION fail_fixture()')
        with self.assertRaises(psycopg.errors.RaiseException):
            self.load('2026-01-05T00:00:00+00:00')
        self.assertEqual([x.model_dump() for x in self.reader.list().items], before)
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], second_at)


if __name__ == '__main__':
    unittest.main()

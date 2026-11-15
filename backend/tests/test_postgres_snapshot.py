"""Synthetic snapshot replacement and rollback in a disposable PostgreSQL DB."""
import os
import sqlite3
import unittest
import uuid
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

try:
    import psycopg
except ImportError:
    psycopg = None

from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_snapshot import SNAPSHOT_LOCK_KEY, load_snapshot
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

        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET markdown='수정 원문',media_json='[\"fixtures/new.jpg\"]' WHERE id=1")
            c.execute('DELETE FROM raw_documents WHERE id=2')
            c.execute("INSERT INTO raw_documents VALUES(3,'note','n3','새 문서',NULL,'2026-01-05','새 원문',NULL,NULL,NULL)")
            c.commit()
        self.load(second_at)
        self.assertIsNone(self.reader.get(2))
        self.assertEqual(self.reader.get(1).images, ['fixtures/new.jpg'])
        self.assertEqual(self.reader.get(3).content, '새 원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], second_at)
        with self.pg() as c:
            ids = {r[0] for r in c.execute("SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='raw_documents'")}
            self.assertEqual(ids, {'1', '3'})
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


    def test_ties_visibility_source_filter_and_source_guard(self):
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET published_at='2026-01-01' WHERE id=2")
            c.commit()
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with patch('pipeline.visibility.feed_mute_sql', return_value=('rd.id <> ?', [1])):
                result = load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00')
        finally:
            source.close()
        self.assertEqual((result['documents'], result['list_rows']), (2, 1))
        self.assertIsNotNone(self.reader.get(1))  # muted in feed, detail preserved
        self.assertEqual(self.reader.list().total, 1)
        self.assertEqual([x.id for x in self.reader.list(source='note').items], [2])
        self.assertEqual(self.reader.list(source='telegram').total, 0)
        self.assertEqual(self.reader.list(page=2, size=1).items, [])
        original = self.reader.snapshot_info()
        with closing(self.fixture.connect()) as unsafe:
            with self.assertRaises(ValueError):
                load_snapshot(unsafe, self.pg, snapshot_at='2026-01-07T00:00:00+00:00')
        self.assertEqual(self.reader.snapshot_info(), original)

    def test_older_snapshot_cannot_replace_newer(self):
        self.load('2026-01-05T00:00:00+00:00')
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET markdown='older data' WHERE id=1")
            c.commit()
        with self.assertRaises(ValueError):
            self.load('2026-01-04T00:00:00+00:00')
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], '2026-01-05T00:00:00+00:00')

    def test_concurrent_loader_waits_for_transaction_lock(self):
        blocker = self.pg()
        blocker.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        failures = []
        def run():
            try:
                self.load('2026-01-05T00:00:00+00:00')
            except Exception as exc:
                failures.append(exc)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline and worker.is_alive():
                with self.pg() as conn:
                    waiting = conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"
                    ).fetchone()[0]
                if waiting:
                    break
                time.sleep(0.02)
            self.assertTrue(waiting, 'loader must wait for the advisory transaction lock')
        finally:
            blocker.commit()
            blocker.close()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertEqual(self.reader.get(1).content, '원문')

    def test_unsupported_source_value_rolls_back_entire_snapshot(self):
        at = '2026-01-06T00:00:00+00:00'
        self.load(at)
        with closing(self.fixture.connect()) as c:
            c.execute('INSERT INTO youtube_digest_jobs VALUES(?,?,?,?,?,?)',
                      (1, 'synthetic', 'pending', sqlite3.Binary(b'\x00\x01'), 0, None))
            c.commit()
        with self.assertRaises(TypeError):
            self.load('2026-01-07T00:00:00+00:00')
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], at)
        with self.pg() as c:
            count = c.execute("SELECT row_count FROM legacy_snapshot_tables WHERE table_name='youtube_digest_jobs'").fetchone()[0]
            self.assertEqual(count, 0)

    def test_source_categories_and_original_rows_preserved(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.executescript("""
                INSERT INTO blog_sources VALUES
                  ('https://example.test','naver','블로그',1),
                  ('https://rss.hankyung.com/feed','rss','뉴스',1),
                  ('https://rss.newsletter.test/feed','rss','기사',1);
                INSERT INTO raw_documents VALUES
                  (3,'blog','news-3','뉴스','https://www.hankyung.com/a','2026-01-04','뉴스 본문',NULL,NULL,NULL),
                  (4,'blog','article-4','기사','https://newsletter.test/a','2026-01-03','기사 본문',NULL,NULL,NULL);
                INSERT INTO entities VALUES (8,'person','합성 인물',NULL);
                INSERT INTO entity_links VALUES (4,8,'person',0.7);
                INSERT INTO follows VALUES (8);
            """)
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = {name: sqlite_feed(source=name) for name in ('blog','news','article','people')}
        self.load('2026-01-06T00:00:00+00:00')
        for name, wanted in expected.items():
            actual = self.reader.list(source=name)
            self.assertEqual(actual.total, wanted.total, name)
            self.assertEqual([x.model_dump() for x in actual.items],
                             [x.model_dump() for x in wanted.items], name)
        with self.pg() as c:
            raw = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'='3'").fetchone()[0]
            self.assertEqual((raw['source_type'], raw['source_id'], raw['markdown'], raw['raw_content']),
                             ('blog','news-3','뉴스 본문',None))
            saved = c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='enrichments'").fetchone()[0]
            self.assertEqual(saved, 2)
            columns = c.execute("SELECT columns FROM legacy_snapshot_tables WHERE table_name='raw_documents'").fetchone()[0]
            self.assertIn('media_json', columns)

    def test_tie_order_matches_sqlite_feed(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET published_at='2026-01-01' WHERE id=2")
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = sqlite_feed()
        self.load('2026-01-06T00:00:00+00:00')
        actual = self.reader.list()
        self.assertEqual([x.model_dump() for x in actual.items], [x.model_dump() for x in expected.items])
        pages = [self.reader.list(page=i, size=1).items for i in (1, 2, 3)]
        self.assertEqual([x.model_dump() for page in pages for x in page],
                         [x.model_dump() for x in expected.items])


if __name__ == '__main__':
    unittest.main()

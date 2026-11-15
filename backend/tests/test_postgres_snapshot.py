"""Synthetic snapshot replacement and rollback in a disposable PostgreSQL DB."""
import os
import json
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
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_rebuild_detail import rebuild_details
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources
from pipeline.postgres_rebuild_timeline import rebuild_source_timeline
from pipeline.postgres_rebuild_system_timeline import rebuild_system_timeline
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
        with closing(self.fixture.connect()) as c:
            c.execute('ALTER TABLE raw_documents ADD COLUMN fetched_at TEXT')
            c.commit()
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
        info = self.reader.snapshot_info()
        self.assertEqual(info['snapshot_at'], first_at)
        self.assertIsNotNone(info['source_observed_at'])
        self.assertGreaterEqual(info['loaded_at'], info['source_observed_at'])

        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET markdown='수정 원문',media_json='[\"fixtures/new.jpg\"]' WHERE id=1")
            c.execute('DELETE FROM raw_documents WHERE id=2')
            c.execute("INSERT INTO raw_documents VALUES(3,'note','n3','새 문서',NULL,'2026-01-05','새 원문',NULL,NULL,NULL,NULL)")
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

    def test_pg_raw_rows_recreate_existing_detail_without_projection(self):
        from pipeline.document_read import _read_sqlite_document
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO entities VALUES(5,'company','다른 회사','000005')")
            c.execute("INSERT INTO entity_links VALUES(1,5,'stock',0.6)")
            c.execute("CREATE INDEX fixture_entity_order ON entity_links(doc_id,entity_id,link_type)")
            c.execute("INSERT INTO raw_documents VALUES(3,'youtube','yt/3','영상',NULL,'2026-01-03','정리본','자막','ok',NULL,NULL)")
            c.execute("INSERT INTO raw_documents VALUES(4,'youtube','yt/4','영상2',NULL,'2026-01-04',NULL,'원 자막','pending',NULL,NULL)")
            c.execute("INSERT INTO youtube_digest_jobs VALUES(4,'원 자막','failed','fixture',0,'합성 오류')")
            c.commit()
            expected = {i: _read_sqlite_document(c, i).model_dump() for i in (1, 2, 3, 4)}
        self.load('2026-01-05T00:00:00+00:00')
        with self.pg() as c:
            saved = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_digests'").fetchone()
            self.assertEqual(saved[0]['digest'], '합성 요약')
            saved = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='channel_reads'").fetchone()
            self.assertEqual(saved[0]['channel'], 'blog:fixture')
        raw_reader = PostgreSQLRawDocumentReader(self.pg)
        for doc_id, document in expected.items():
            self.assertEqual(raw_reader.get(doc_id).model_dump(), document)
        self.assertIsNone(raw_reader.get(999))
        # Raw reader must not depend on the cached response projection.
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document = jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps("projection only"),))
        self.assertEqual(raw_reader.get(1).model_dump(), expected[1])

    def test_source_timeline_filters_and_pagination_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(3,'blog','b3','둘째','https://example.test/post','2026-01-01','내용',NULL,NULL,'[]',NULL)")
            c.commit()
            expected = {key: timeline(c, scope='sources', until='2026-01-02T00:00:00Z', **params)
                        for key, params in {'all': {}, 'blog': {'source': 'blog'},
                                            'channel': {'channel': 'blog:https://example.test/'},
                                            'empty': {'source': 'youtube'},
                                            'topic': {'topic': '합성 회사'},
                                            'page2': {'size': 1, 'page': 2}}.items()}
        self.load('2026-01-05T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for key, params in {'all': {}, 'blog': {'source': 'blog'},
                            'channel': {'channel': 'blog:https://example.test/'},
                            'empty': {'source': 'youtube'}, 'topic': {'topic': '합성 회사'},
                            'page2': {'size': 1, 'page': 2}}.items():
            actual = reader.timeline(until='2026-01-02T00:00:00Z', **params)
            self.assertEqual([i.model_dump() for i in actual.items], [i.model_dump() for i in expected[key].items], key)
            self.assertEqual(actual.has_more, expected[key].has_more, key)

    def test_system_and_mixed_timeline_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO source_digests VALUES (1,'person','합성 인물','저장 요약',1,'2026-01-01')")
            c.commit()
            cases = {'system': {'scope': 'system'}, 'person': {'scope': 'system', 'kind': 'person'},
                     'all': {'scope': 'all'}, 'topic': {'scope': 'all', 'topic': '합성 회사'}}
            expected = {key: timeline(c, until='2026-01-06T00:00:00Z', **params) for key, params in cases.items()}
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for key, params in cases.items():
            actual = reader.timeline(until='2026-01-06T00:00:00Z', **params)
            self.assertEqual([i.model_dump() for i in actual.items], [i.model_dump() for i in expected[key].items], key)
            self.assertEqual(actual.has_more, expected[key].has_more, key)

    def test_rebuild_system_timeline_from_raw_and_rollback(self):
        with closing(self.fixture.connect()) as c:
            c.executescript("""
            INSERT INTO source_digests VALUES (1,'person','인물','요약',2,'2026-01-01');
            INSERT INTO transcript_follow VALUES ('MU','Micron',1);
            INSERT INTO transcripts VALUES (1,1,'MU',2025,'Q4','통화 요약','2026-01-01');
            INSERT INTO trade_follow VALUES ('1234','품목','그룹',1);
            INSERT INTO trade_stats VALUES ('1234','2025-12','2026-01-01');
            INSERT INTO narratives VALUES (1,'주제',1,'제목','본문',1,'2026-01-01');
            INSERT INTO reports VALUES (1,'주제','보고서','본문','[]','2026-01-01');
            INSERT INTO scenarios VALUES ('주제','답변',NULL,'2026-01-01');
            """)
            c.commit()
        self.load('2026-01-06T00:00:00+00:00')
        with self.pg() as c:
            expected = c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall()
            self.assertEqual(len(expected), 7)
            c.execute('DELETE FROM timeline_system_projection')
        self.assertEqual(rebuild_system_timeline(self.pg), len(expected))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall(), expected)
            c.execute("CREATE FUNCTION fail_system() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
            c.execute('CREATE TRIGGER fail_system BEFORE INSERT ON timeline_system_projection FOR EACH ROW EXECUTE FUNCTION fail_system()')
        with self.assertRaises(psycopg.errors.RaiseException):
            rebuild_system_timeline(self.pg)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall(), expected)

    def test_rebuild_source_timeline_from_raw_and_failure_rolls_back(self):
        self.load('2026-01-06T00:00:00+00:00')
        with self.pg() as c:
            expected = c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall()
            self.assertTrue(expected)
            c.execute('DELETE FROM timeline_source_projection')
        self.assertEqual(rebuild_source_timeline(self.pg), len(expected))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall(), expected)
            c.execute('DELETE FROM timeline_source_metadata WHERE document_id=%s', (expected[0][1],))
        with self.assertRaises(ValueError):
            rebuild_source_timeline(self.pg)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall(), expected)

    def test_timeline_submillisecond_ties_and_until_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(8,'telegram','t/8','A',NULL,'2026-01-01T00:00:00.000400Z','내용',NULL,NULL,'[]',NULL)")
            c.execute("INSERT INTO raw_documents VALUES(9,'telegram','t/9','B',NULL,'2026-01-01T00:00:00.000100Z','내용',NULL,NULL,'[]',NULL)")
            c.execute("INSERT INTO telegram_channels VALUES('t','채널',1)")
            c.execute("INSERT INTO channel_reads VALUES ('telegram:t','2026-01-01T00:00:00.000200Z',NULL)")
            c.commit()
            expected = [timeline(c, scope='sources', channel='telegram:t', size=1, page=page,
                                 until='2026-01-01T00:00:00.000200Z') for page in (1, 2)]
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for page, wanted in enumerate(expected, 1):
            actual = reader.timeline(scope='sources', channel='telegram:t', size=1, page=page,
                                     until='2026-01-01T00:00:00.000200Z')
            self.assertEqual([i.id for i in actual.items], [i.id for i in wanted.items])
            self.assertEqual(actual.has_more, wanted.has_more)
        from pipeline.timeline import channels
        with closing(self.fixture.connect()) as c:
            expected_channels = channels(c, until='2026-01-01T00:00:00.000200Z')
        self.assertEqual(reader.channels(until='2026-01-01T00:00:00.000200Z').model_dump(), expected_channels.model_dump())

    def test_channel_directory_matches_sqlite_and_remains_readonly(self):
        from pipeline.timeline import channels
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO channel_reads VALUES ('*','2026-01-01T12:00:00Z',NULL)")
            c.commit()
            expected = channels(c, until='2026-01-06T00:00:00Z')
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        actual = reader.channels(until='2026-01-06T00:00:00Z')
        self.assertEqual(actual.model_dump(), expected.model_dump())
        self.assertEqual(reader.channels(until='2026-01-06T00:00:00Z').model_dump(), expected.model_dump())

    def test_rebuild_details_from_pg_and_rollback_on_failure(self):
        self.load('2026-01-05T00:00:00+00:00')
        original = self.reader.get(1).model_dump()
        feed = [x.model_dump() for x in self.reader.list().items]
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document=jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps('stale'),))
        self.assertEqual(rebuild_details(self.pg), 2)
        self.assertEqual(self.reader.get(1).model_dump(), original)
        self.assertEqual([x.model_dump() for x in self.reader.list().items], feed)
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document=jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps('stale'),))
            c.execute("CREATE FUNCTION fail_rebuild() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id=2 THEN RAISE EXCEPTION 'synthetic failure'; END IF; RETURN NEW; END $$")
            c.execute('CREATE TRIGGER fail_rebuild BEFORE UPDATE ON document_projection FOR EACH ROW EXECUTE FUNCTION fail_rebuild()')
        with self.assertRaises(psycopg.errors.RaiseException):
            rebuild_details(self.pg)
        self.assertEqual(self.reader.get(1).content, 'stale')

    def test_refuses_non_fixture_target_schema(self):
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            factory = lambda: psycopg.connect(self.dsn, options='-c search_path=public')
            with self.assertRaises(ValueError):
                load_snapshot(source, factory, snapshot_at='2026-01-05T00:00:00+00:00')
        finally:
            source.close()

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

    def test_source_filter_uses_existing_sqlite_tie_order_across_pages(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.executescript("""
                INSERT INTO raw_documents VALUES
                  (3,'transcript','t3','컨콜3',NULL,'2026-01-05','본문3',NULL,NULL,NULL,NULL),
                  (4,'transcript','t4','컨콜4',NULL,'2026-01-05','본문4',NULL,NULL,NULL,NULL);
                CREATE INDEX fixture_source_order ON raw_documents(source_type, published_at DESC, id DESC);
                CREATE INDEX fixture_global_order ON raw_documents(published_at DESC, id ASC);
            """)
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = sqlite_feed(source='transcript', size=1, page=1)
            expected2 = sqlite_feed(source='transcript', size=1, page=2)
            global_order = [x.id for x in sqlite_feed().items if x.source_type == 'transcript']
        self.assertNotEqual(global_order, [expected.items[0].id, expected2.items[0].id])
        self.load('2026-01-06T00:00:00+00:00')
        actual = self.reader.list(source='transcript', size=1, page=1)
        actual2 = self.reader.list(source='transcript', size=1, page=2)
        self.assertEqual([x.model_dump() for x in actual.items], [x.model_dump() for x in expected.items])
        self.assertEqual([x.model_dump() for x in actual2.items], [x.model_dump() for x in expected2.items])

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
                  (3,'blog','news-3','뉴스','https://www.hankyung.com/a','2026-01-04','뉴스 본문',NULL,NULL,NULL,NULL),
                  (4,'blog','article-4','기사','https://newsletter.test/a','2026-01-03','기사 본문',NULL,NULL,NULL,NULL);
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

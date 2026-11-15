"""Exercise writes only in a fresh schema of a disposable PostgreSQL server."""
import os
import struct
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from pipeline.postgres_ingest_fixture import store_document, store_raw_doc, store_embedding, claim_enrichment, finish_enrichment, fail_enrichment, publish_projection
from pipeline.base import SourceRef
from pipeline.connectors.blog import BlogConnector
from pipeline.connectors.youtube import YouTubeConnector
from pipeline.postgres_youtube_digest_fixture import queue as queue_video, finish as finish_video
from pipeline.postgres_video_import_fixture import import_videos
from tests.test_document_read_boundary import DocumentReadBoundaryTests
from routers import spine_doc
from pipeline.postgres_ingest_rebuild_fixture import rebuild
from pipeline.postgres_ingest_coordinator_fixture import FixtureCoordinator
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_search_feed import search_feed


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class IngestFixtureTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        p = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (p.get('host'), p.get('dbname'), p.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())

    def drop_schema(self):
        with psycopg.connect(self.dsn) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def pg(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def put(self, text):
        with self.pg() as c:
            return store_document(c, source_type='fixture', source_id='1', title='title', markdown=text)

    def test_duplicate_update_stale_and_aba(self):
        a = self.put('A')
        self.assertEqual(self.put('A')['status'], 'unchanged')
        with self.pg() as c:
            first = claim_enrichment(c, document_id=a['id'])
        b = self.put('B')
        self.assertEqual((b['status'], b['revision']), ('updated', 2))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_enrichments').fetchone()[0], 0)
            self.assertFalse(finish_enrichment(c, document_id=a['id'], **first, summary='late', model='fixture'))
        again = self.put('A')
        self.assertEqual(again['revision'], 3)
        with self.pg() as c:
            self.assertFalse(finish_enrichment(c, document_id=a['id'], **first, summary='old A', model='fixture'))
            current = claim_enrichment(c, document_id=a['id'])
            self.assertTrue(finish_enrichment(c, document_id=a['id'], **current, summary='new A', model='fixture'))
            self.assertEqual(c.execute('SELECT summary FROM ingest_enrichments').fetchone()[0], 'new A')

    def test_rollback_does_not_leave_document_or_enrichment(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.pg() as c:
                row = store_document(c, source_type='fixture', source_id='1', title='t', markdown='a')
                job = claim_enrichment(c, document_id=row['id'])
                finish_enrichment(c, document_id=row['id'], **job, summary='s', model='fixture')
                raise RuntimeError('rollback')
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_documents').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_enrichments').fetchone()[0], 0)

    def test_same_content_updates_nonempty_media_and_preserves_empty_media(self):
        self.put('A')
        with self.pg() as c:
            row = store_document(c, source_type='fixture', source_id='1', title='ignored', markdown='A', media=['one'])
            self.assertEqual((row['status'], row['revision']), ('unchanged', 1))
            store_document(c, source_type='fixture', source_id='1', title='ignored', markdown='A', media=[])
            self.assertEqual(c.execute('SELECT title, media_json FROM ingest_documents').fetchone(), ('title', ['one']))

    def test_failed_retry_rejects_old_token_and_keyword_upgrade(self):
        row = self.put('A')
        with self.pg() as c:
            first = claim_enrichment(c, document_id=row['id'])
            self.assertIsNone(claim_enrichment(c, document_id=row['id']))
            self.assertTrue(fail_enrichment(c, document_id=row['id'], **first))
            retry = claim_enrichment(c, document_id=row['id'])
            self.assertFalse(finish_enrichment(c, document_id=row['id'], **first, summary='late', model='fixture'))
            self.assertTrue(finish_enrichment(c, document_id=row['id'], **retry, summary='k', model='keyword'))
            self.assertIsNone(claim_enrichment(c, document_id=row['id']))
            upgrade = claim_enrichment(c, document_id=row['id'], upgrade_keyword=True)
            self.assertTrue(finish_enrichment(c, document_id=row['id'], **upgrade, summary='better', model='fixture'))
            self.assertIsNone(claim_enrichment(c, document_id=row['id'], upgrade_keyword=True))

    def test_concurrent_claim_has_one_winner(self):
        row = self.put('A')
        barrier = threading.Barrier(4)
        def worker(_):
            barrier.wait(timeout=10)
            with self.pg() as c:
                return claim_enrichment(c, document_id=row['id'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(worker, range(4)))
        self.assertEqual(sum(job is not None for job in jobs), 1)

    def test_raw_fields_update_only_when_content_changes(self):
        with self.pg() as c:
            store_document(c, source_type='fixture', source_id='1', title='t', markdown='A',
                           raw_content='raw A', url='one', published_at='2026-01-01', digest_status='ok')
            store_document(c, source_type='fixture', source_id='1', title='ignored', markdown='A', raw_content='ignored')
            self.assertEqual(c.execute('SELECT raw_content,url,published_at,digest_status FROM ingest_documents').fetchone(),
                             ('raw A', 'one', '2026-01-01', 'ok'))
            store_document(c, source_type='fixture', source_id='1', title='t2', markdown='B',
                           raw_content='raw B', url='two', published_at='2026-01-02', digest_status='failed')
            self.assertEqual(c.execute('SELECT raw_content,url,published_at,digest_status FROM ingest_documents').fetchone(),
                             ('raw B', 'two', '2026-01-02', 'failed'))

    def test_concurrent_duplicate(self):
        barrier = threading.Barrier(4)
        def worker(_):
            barrier.wait(timeout=10)
            return self.put('same')
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(worker, range(4)))
        self.assertEqual(sorted(r['status'] for r in rows), ['new', 'unchanged', 'unchanged', 'unchanged'])
        self.assertEqual(len({r['id'] for r in rows}), 1)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_documents').fetchone()[0], 1)

    def test_projection_publication_failure_retry_and_media_dirty(self):
        row = self.put('A')
        with self.pg() as c:
            c.execute('CREATE TABLE fixture_projection(document_id BIGINT PRIMARY KEY, body TEXT)')
        def publish(c, doc_id):
            c.execute('INSERT INTO fixture_projection SELECT id,markdown FROM ingest_documents WHERE id=%s '
                      'ON CONFLICT(document_id) DO UPDATE SET body=excluded.body', (doc_id,))
        with self.pg() as c:
            self.assertTrue(publish_projection(c, document_id=row['id'], version=1, publish=publish))
        self.put('B')
        def broken(c, doc_id):
            publish(c, doc_id)
            raise RuntimeError('projection failure')
        with self.assertRaisesRegex(RuntimeError, 'projection failure'):
            with self.pg() as c:
                publish_projection(c, document_id=row['id'], version=2, publish=broken)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT body FROM fixture_projection').fetchone()[0], 'A')
            self.assertEqual(c.execute('SELECT projection_version,projected_version FROM ingest_documents').fetchone(), (2, 1))
            self.assertTrue(publish_projection(c, document_id=row['id'], version=2, publish=publish))
            self.assertEqual(c.execute('SELECT body FROM fixture_projection').fetchone()[0], 'B')
            store_document(c, source_type='fixture', source_id='1', title='title', markdown='B', media=['image'])
            self.assertFalse(publish_projection(c, document_id=row['id'], version=2, publish=publish))
            self.assertEqual(c.execute('SELECT projection_version,projected_version FROM ingest_documents').fetchone(), (3, 2))
            self.assertTrue(publish_projection(c, document_id=row['id'], version=3, publish=publish))

    def test_worker_recovery_is_explicit_and_invalidates_old_token(self):
        row = self.put('A')
        with self.pg() as c:
            first = claim_enrichment(c, document_id=row['id'], worker_id='worker-1')
            worker, started = c.execute('SELECT worker_id,started_at FROM ingest_enrichment_jobs').fetchone()
            self.assertEqual(worker, 'worker-1')
            self.assertIsNotNone(started)
            self.assertIsNone(claim_enrichment(c, document_id=row['id'], worker_id='worker-2'))
            # Caller must establish that worker-1 is stopped before releasing it.
            self.assertTrue(fail_enrichment(c, document_id=row['id'], **first))
            retry = claim_enrichment(c, document_id=row['id'], worker_id='worker-2')
            self.assertFalse(finish_enrichment(c, document_id=row['id'], **first, summary='late', model='fixture'))
            self.assertTrue(finish_enrichment(c, document_id=row['id'], **retry, summary='new', model='fixture'))

    def test_ingest_to_existing_feed_and_lexical_search_generation(self):
        with self.pg() as c:
            doc = store_document(c, source_type='note', source_id='test', title='반도체 전망',
                                 markdown='반도체 원문', raw_content='반도체 원문',
                                 published_at='2026-01-01', media=['image.png'])
            job = claim_enrichment(c, document_id=doc['id'])
            finish_enrichment(c, document_id=doc['id'], **job, summary='저장 요약', model='fixture')
            first = rebuild(c)
        reader = PostgreSQLDocumentReader(self.pg)
        item = reader.list(source='note').items[0]
        self.assertEqual((item.title, item.summary, item.content, item.images),
                         ('반도체 전망', '저장 요약', '반도체 원문', ['image.png']))
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            index = SearchSnapshot.from_postgres(c)
            result = search_feed(c, index, '반도체')
            self.assertEqual((result.total, result.items[0].summary), (1, '저장 요약'))
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='새 제목',
                           markdown='배터리 원문', published_at='2026-01-02')
            self.assertEqual(reader.list().items[0].summary, '저장 요약')
            second = rebuild(c)
        self.assertNotEqual(first, second)
        self.assertEqual((reader.list().items[0].content, reader.list().items[0].summary), ('배터리 원문', None))
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with self.assertRaisesRegex(ValueError, 'generation expired'):
                search_feed(c, index, '반도체')
            index.close()
            index = SearchSnapshot.from_postgres(c)
            self.assertEqual(search_feed(c, index, '배터리').total, 1)
            self.assertEqual(search_feed(c, index, '반도체').total, 0)
            index.close()

    def test_rebuild_failure_keeps_previous_feed_and_retry_succeeds(self):
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='old', markdown='old')
            generation = rebuild(c)
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='new', markdown='new', media='invalid')
        with self.assertRaises(ValueError):
            with self.pg() as c:
                rebuild(c)
        reader = PostgreSQLDocumentReader(self.pg)
        self.assertEqual(reader.list().items[0].title, 'old')
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0], generation)
            store_document(c, source_type='note', source_id='test', title='new', markdown='new', media=['fixed'])
            rebuild(c)
        self.assertEqual(reader.list().items[0].title, 'new')

    def test_rebuild_rejects_existing_non_ingest_snapshot(self):
        with self.pg() as c:
            c.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) "
                      "VALUES (TRUE,'2026-01-01T00:00:00+00:00',now(),0,0,%s)", (uuid.uuid4(),))
        with self.assertRaisesRegex(ValueError, 'another snapshot'):
            with self.pg() as c:
                rebuild(c)

    def test_search_index_failure_keeps_old_generation_until_retry(self):
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='반도체', markdown='반도체 자료')
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        first = coordinator.rebuild()
        self.assertEqual(coordinator.search('반도체').total, 1)
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='배터리', markdown='배터리 자료')
        def broken(*args):
            raise RuntimeError('index failed')
        coordinator.index_factory = broken
        with self.assertRaisesRegex(RuntimeError, 'index failed'):
            coordinator.rebuild()
        self.assertEqual(coordinator.list().items[0].title, '반도체')
        self.assertEqual(coordinator.search('반도체').total, 1)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0], first)
        coordinator.index_factory = SearchSnapshot
        self.assertNotEqual(coordinator.rebuild(), first)
        self.assertEqual(coordinator.list().items[0].title, '배터리')
        self.assertEqual(coordinator.search('배터리').total, 1)
        self.assertEqual(coordinator.search('반도체').total, 0)

    def test_read_waits_during_generation_switch(self):
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='A', markdown='old')
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        with self.pg() as c:
            store_document(c, source_type='note', source_id='test', title='B', markdown='new')
        entered, release = threading.Event(), threading.Event()
        def slow(generation, rows, vectors):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test timed out')
            return SearchSnapshot(generation, rows, vectors)
        coordinator.index_factory = slow
        with ThreadPoolExecutor(max_workers=2) as pool:
            building = pool.submit(coordinator.rebuild)
            self.assertTrue(entered.wait(5))
            reading = pool.submit(coordinator.list)
            self.assertFalse(reading.done())
            release.set()
            building.result(timeout=5)
            self.assertEqual(reading.result(timeout=5).items[0].title, 'B')

    def test_current_vector_search_and_stale_vector_rejection(self):
        vector = struct.pack('<384f', 1.0, *([0.0] * 383))
        with self.pg() as c:
            row = store_document(c, source_type='note', source_id='test', title='제목', markdown='원문')
            self.assertTrue(store_embedding(c, document_id=row['id'], revision=1, embedding=vector))
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        self.assertEqual(coordinator.search('없는단어', vector=vector).total, 1)
        with self.pg() as c:
            changed = store_document(c, source_type='note', source_id='test', title='제목', markdown='변경')
            self.assertFalse(store_embedding(c, document_id=row['id'], revision=1, embedding=vector))
        coordinator.rebuild()
        self.assertEqual(coordinator.search('없는단어', vector=vector).total, 0)
        with self.pg() as c:
            self.assertTrue(store_embedding(c, document_id=row['id'], revision=changed['revision'], embedding=vector))
        coordinator.rebuild()
        self.assertEqual(coordinator.search('없는단어', vector=vector).total, 1)

    def test_rss_connector_to_blog_feed_and_search_without_network(self):
        entry = {'url': 'https://example.test/posts/1', 'title': '반도체 기사',
                 'content': '<p>짧은 본문</p>', 'published_at': '2026-01-02'}
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url', return_value=('rss', 'https://example.test/feed')), \
             patch('pipeline.connectors.blog.scrape_rss', return_value=([entry], '합성 매체')), \
             patch('services.blog_service.fetch_full_content', return_value='<p>반도체 전체 원문</p>'):
            docs = BlogConnector(['https://example.test/feed']).fetch(SourceRef('https://example.test/feed'))
        with self.pg() as c:
            c.execute("INSERT INTO ingest_blog_sources VALUES ('https://example.test/feed','rss','합성 매체')")
            saved = store_raw_doc(c, docs[0])
            job = claim_enrichment(c, document_id=saved['id'])
            finish_enrichment(c, document_id=saved['id'], **job, summary='합성 요약', model='fixture')
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        result = coordinator.search('반도체', source='article')
        self.assertEqual(result.total, 1)
        item = result.items[0]
        self.assertEqual((item.title, item.summary, item.content, item.channel),
                         ('반도체 기사', '합성 요약', '반도체 전체 원문', '합성 매체'))
        self.assertEqual(coordinator.list(source='article').total, 1)
        self.assertEqual(coordinator.reader.get(saved['id']).summary, '합성 요약')
        with self.pg() as c:
            self.assertEqual(store_raw_doc(c, docs[0])['status'], 'unchanged')
            docs[0].raw_content = '<p>배터리 새 본문</p>'
            self.assertEqual(store_raw_doc(c, docs[0])['status'], 'updated')
        coordinator.rebuild()
        self.assertEqual(coordinator.search('반도체', source='article').items[0].summary, None)
        self.assertEqual(coordinator.search('배터리', source='article').total, 1)

    def test_blog_connector_naver_full_and_missing_url_title_fallback(self):
        posts = [
            {'url': 'https://blog.naver.com/synthetic/1', 'title': '긴 글', 'content': 'a' * 700},
            {'url': '', 'title': 'URL 없는 글', 'content': '본문'},
        ]
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url', return_value=('rss', 'https://example.test/feed')), \
             patch('pipeline.connectors.blog.scrape_rss', return_value=(posts, '합성')), \
             patch('services.blog_service.fetch_full_content', return_value='b' * 800) as fetch:
            docs = BlogConnector().fetch(SourceRef('https://example.test/feed'))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(docs[0].raw_content, 'b' * 800)
        self.assertEqual(docs[1].source_id, 'URL 없는 글')

    def test_youtube_connector_transcript_to_feed_detail_and_search(self):
        ref = SourceRef('abc123def45', meta={'title': '합성 영상', 'published': '2026-01-02',
                                            'channel_id': 'UCfixture'})
        with patch('pipeline.connectors.youtube.fetch_transcript', return_value='합성 반도체 자막 원문'):
            docs = YouTubeConnector(video_ids=[ref.key]).fetch(ref)
        with patch('pipeline.connectors.youtube.fetch_transcript', return_value=None):
            self.assertEqual(YouTubeConnector(video_ids=[ref.key]).fetch(ref), [])
        self.assertEqual(docs[0].source_id, 'UCfixture/abc123def45')
        with self.pg() as c:
            c.execute("INSERT INTO ingest_youtube_channels VALUES ('UCfixture','합성 영상 채널')")
            saved = store_raw_doc(c, docs[0])
            job = claim_enrichment(c, document_id=saved['id'])
            finish_enrichment(c, document_id=saved['id'], **job, summary='합성 짧은 요약', model='fixture')
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        result = coordinator.search('반도체', source='youtube')
        self.assertEqual(result.total, 1)
        self.assertEqual((result.items[0].channel, result.items[0].summary, result.items[0].content),
                         ('합성 영상 채널', '합성 짧은 요약', '합성 반도체 자막 원문'))
        detail = coordinator.reader.get(saved['id'])
        self.assertEqual((detail.digest_status, detail.transcript, detail.video_digest),
                         ('pending', '합성 반도체 자막 원문', None))

    def test_video_digest_retains_transcript_and_previous_summary(self):
        transcript = '원본 자막 ' * 30
        with self.pg() as c:
            doc = store_document(c, source_type='youtube', source_id='UCfixture/abc123def45',
                                 title='영상', markdown=transcript, raw_content=transcript, digest_status='pending')
            summary_job = claim_enrichment(c, document_id=doc['id'])
            finish_enrichment(c, document_id=doc['id'], **summary_job, summary='기존 요약', model='fixture')
            first = queue_video(c, doc['id'])
            self.assertIsNone(queue_video(c, doc['id']))
            self.assertTrue(finish_video(c, doc['id'], revision=first['revision'], token=first['token']))
            retry = queue_video(c, doc['id'])
            self.assertFalse(finish_video(c, doc['id'], revision=first['revision'], token=first['token'], digest='늦은 정리'))
            self.assertTrue(finish_video(c, doc['id'], revision=retry['revision'], token=retry['token'], digest='새 정리본'))
            self.assertEqual(c.execute('SELECT summary FROM ingest_enrichment_history').fetchone()[0], '기존 요약')
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs').fetchone()[0], 'pending')
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        detail = coordinator.reader.get(doc['id'])
        self.assertEqual(detail.digest_status, 'ok')
        self.assertEqual(detail.transcript, transcript)
        self.assertIn('새 정리본', detail.video_digest)
        self.assertIsNone(detail.summary)

    def test_video_digest_rejects_result_when_transcript_changed(self):
        with self.pg() as c:
            doc = store_document(c, source_type='youtube', source_id='x', title='영상',
                                 markdown='가' * 100, raw_content='가' * 100, digest_status='pending')
            job = queue_video(c, doc['id'])
            store_document(c, source_type='youtube', source_id='x', title='영상',
                           markdown='나' * 100, raw_content='나' * 100, digest_status='pending')
            self.assertFalse(finish_video(c, doc['id'], revision=job['revision'], token=job['token'], digest='오래된 정리'))
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        detail = coordinator.reader.get(doc['id'])
        self.assertEqual((detail.transcript, detail.video_digest), ('나' * 100, None))

    def test_import_existing_video_preserves_display_and_rejects_duplicate(self):
        source_fixture = DocumentReadBoundaryTests('test_raw_fallback_and_missing')
        source_fixture.setUp()
        self.addCleanup(source_fixture.tearDown)
        with source_fixture.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES (10,'youtube','UCfixture/abc123def45','영상','https://example.test',"
                      "'2026-01-01','기존 정리본','기존 정리본','ok',NULL)")
            c.execute("INSERT INTO enrichments VALUES (10,10,'기존 요약','fixture','2026-01-01')")
            c.execute("INSERT INTO youtube_digest_jobs VALUES (10,'원래 자막','ok','old-token',1,NULL)")
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','합성 채널',1)")
        with patch('routers.spine_feed.resolve_channels', return_value={10: {'name': '합성 채널', 'kind': 'youtube', 'key': 'UCfixture'}}):
            expected = spine_doc.get_document(10)
        with source_fixture.connect() as source:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            with self.pg() as target:
                self.assertEqual(import_videos(source, target, [10]), 1)
            with self.assertRaises(psycopg.errors.UniqueViolation):
                with self.pg() as target:
                    import_videos(source, target, [10])
        coordinator = FixtureCoordinator(self.pg)
        self.addCleanup(coordinator.close)
        coordinator.rebuild()
        actual = coordinator.reader.get(10)
        for field in ('id','title','content','summary','digest_status','video_digest','transcript','channel'):
            self.assertEqual(getattr(actual, field), getattr(expected, field), field)
        with self.pg() as c:
            created = store_document(c, source_type='note', source_id='new', title='n', markdown='n')
            self.assertGreater(created['id'], 10)

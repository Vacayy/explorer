"""Exercise writes only in a fresh schema of a disposable PostgreSQL server."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg import sql
from pipeline.postgres_ingest_fixture import store_document, claim_enrichment, finish_enrichment, fail_enrichment, publish_projection


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

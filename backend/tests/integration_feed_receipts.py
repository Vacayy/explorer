"""Run only against an explicitly disposable PostgreSQL database."""
import os
import tempfile
import unittest
import uuid

import psycopg

from pipeline import feed_receipts, postgres_collect_runs, postgres_feed_scrap
from pipeline.base import RawDoc
from pipeline.feed_backlog import FeedBacklog


@unittest.skipUnless(os.environ.get('FEED_TEST_DSN'), 'requires disposable PostgreSQL')
class FeedReceiptTest(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['FEED_TEST_DSN'], autocommit=True)
        self.conn.execute('CREATE TEMP TABLE collect_runs (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,'
                          'label TEXT NOT NULL,started_at TEXT NOT NULL,outcome TEXT NOT NULL,detail TEXT,'
                          "requests_json TEXT NOT NULL DEFAULT '{}',model_calls INTEGER,result_json TEXT NOT NULL DEFAULT '{}')")
        self.conn.execute('CREATE TEMP TABLE publication (value INTEGER)')
        self.conn.execute('CREATE TEMP TABLE legacy_supplement_tables (table_name TEXT, columns TEXT[], row_count INTEGER)')
        self.conn.execute('CREATE TEMP TABLE legacy_supplement_rows (table_name TEXT, row_ordinal BIGINT, row_data JSONB)')
        self.conn.execute("INSERT INTO legacy_supplement_tables VALUES ('scrap_links',ARRAY['url','doc_id','status'],0)")
        self.token = str(uuid.uuid4())

    def tearDown(self):
        self.conn.close()

    def test_rollback_before_commit_and_retry_after_commit(self):
        def interrupted():
            self.conn.execute('INSERT INTO publication VALUES (1)')
            raise RuntimeError('simulated precommit interruption')

        with self.assertRaises(RuntimeError):
            feed_receipts.publish_once(self.conn, self.token, '2026-01-01', interrupted)
        self.assertFalse(feed_receipts.committed(self.conn, self.token))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM publication').fetchone()[0], 0)
        self.assertTrue(feed_receipts.publish_once(self.conn, self.token, '2026-01-01',
                         lambda: self.conn.execute('INSERT INTO publication VALUES (1)')))
        self.assertTrue(feed_receipts.committed(self.conn, self.token))
        self.assertFalse(feed_receipts.publish_once(self.conn, self.token, '2026-01-01',
                          lambda: self.fail('receipt must prevent duplicate publish')))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM publication').fetchone()[0], 1)

    def test_rejects_invalid_and_duplicate_receipts(self):
        with self.assertRaises(ValueError):
            feed_receipts.committed(self.conn, 'invalid')
        for _ in range(2):
            postgres_collect_runs.record(self.conn, feed_receipts.LABEL, '2026-01-01', f'applied: {self.token}')
        with self.assertRaises(RuntimeError):
            feed_receipts.committed(self.conn, self.token)

    def test_restart_after_pg_commit_before_local_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'feed.sqlite')
            queue = FeedBacklog(path)
            queue.enqueue('blog', 'reference', RawDoc('blog', 'document'))
            seq = queue.next()[0]
            token = queue.begin_publication(seq)
            feed_receipts.publish_once(self.conn, token, '2026-01-01',
                                       lambda: self.conn.execute('INSERT INTO publication VALUES (1)'))
            queue.close()  # interruption before local floors / acknowledgement
            queue = FeedBacklog(path)
            self.assertEqual(queue.intent(), (token, seq))
            self.assertFalse(feed_receipts.publish_once(self.conn, token, '2026-01-01',
                             lambda: self.fail('must not publish twice')))
            queue.finish_publication(token, receipt_confirmed=feed_receipts.committed(self.conn, token))
            self.assertIsNone(queue.intent())
            self.assertIsNone(queue.next())
            self.assertEqual(self.conn.execute('SELECT count(*) FROM publication').fetchone()[0], 1)
            queue.close()

    def test_scrap_ledger_compare_and_atomic_publication(self):
        first = {'url': 'https://example.test/one', 'doc_id': 10, 'status': 'ok'}
        other = {'url': 'https://example.test/two', 'doc_id': 20, 'status': 'ok'}
        with self.assertRaises(ValueError):
            postgres_feed_scrap.apply(self.conn, before=None, after=first)
        with self.conn.transaction():
            postgres_feed_scrap.apply(self.conn, before=None, after=other)

        def failed():
            postgres_feed_scrap.apply(self.conn, before=None, after=first)
            raise RuntimeError('simulated failure')
        with self.assertRaises(RuntimeError):
            feed_receipts.publish_once(self.conn, self.token, '2026-01-01', failed)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM legacy_supplement_rows').fetchone()[0], 1)
        feed_receipts.publish_once(self.conn, self.token, '2026-01-01',
                                   lambda: postgres_feed_scrap.apply(self.conn, before=None, after=first))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM legacy_supplement_rows').fetchone()[0], 2)
        self.assertEqual(self.conn.execute('SELECT row_count FROM legacy_supplement_tables').fetchone()[0], 2)
        with self.assertRaises(RuntimeError), self.conn.transaction():
            postgres_feed_scrap.apply(self.conn, before=None, after=first)
        changed = {**first, 'doc_id': 11}
        with self.conn.transaction():
            postgres_feed_scrap.apply(self.conn, before=first, after=changed)
        self.assertEqual(self.conn.execute('SELECT row_count FROM legacy_supplement_tables').fetchone()[0], 2)
        with self.assertRaises(RuntimeError), self.conn.transaction():
            postgres_feed_scrap.apply(self.conn, before=first, after=changed)

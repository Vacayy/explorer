"""Exercise writes only in a fresh schema of a disposable PostgreSQL server."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg import sql
from pipeline.postgres_ingest_fixture import store_document, apply_enrichment


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
            self.assertTrue(apply_enrichment(c, document_id=a['id'], revision=a['revision'], summary='a', model='fixture'))
        b = self.put('B')
        self.assertEqual((b['status'], b['revision']), ('updated', 2))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_enrichments').fetchone()[0], 0)
            self.assertFalse(apply_enrichment(c, document_id=a['id'], revision=1, summary='late', model='fixture'))
        again = self.put('A')
        self.assertEqual(again['revision'], 3)
        with self.pg() as c:
            self.assertFalse(apply_enrichment(c, document_id=a['id'], revision=1, summary='old A', model='fixture'))
            self.assertTrue(apply_enrichment(c, document_id=a['id'], revision=3, summary='new A', model='fixture'))
            self.assertEqual(c.execute('SELECT summary FROM ingest_enrichments').fetchone()[0], 'new A')

    def test_rollback_does_not_leave_document_or_enrichment(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.pg() as c:
                row = store_document(c, source_type='fixture', source_id='1', title='t', markdown='a')
                apply_enrichment(c, document_id=row['id'], revision=row['revision'], summary='s', model='fixture')
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

"""Value-chain report records on the candidate PG schema: written stage by stage, read before the collected rows."""
import os
import types
import unittest
import uuid

import psycopg
from psycopg import sql

from pipeline import postgres_chain_reports as reports


def legacy_module(collected):
    module = types.SimpleNamespace(NOTE_MODEL='note', SYNTH_MODEL='synth', WRITER_MODEL='writer')
    module.read = lambda rid: collected.get(rid)
    module.history = lambda root, limit=10: [{'id': rid, 'root': root, 'status': 'done', 'outline': 'bottom_up',
                                              'created_at': '2026-01-01', 'finished_at': None} for rid in sorted(collected)][:limit]
    module._cached_note = lambda key, h: 'collected note' if (key, h) == ('dram', 'old') else None
    return module


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class ChainReportRecordTests(unittest.TestCase):
    def setUp(self):
        self.dsn, self.schema = os.environ['REFACTOR_POSTGRES_DSN'], 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as pg:
            pg.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop)
        with self.target() as pg:
            reports.initialize(pg)
            pg.execute('CREATE TABLE candidate_job_runs (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),job TEXT NOT NULL,'
                       'status TEXT NOT NULL,summary TEXT,duration_ms BIGINT,ran_at TEXT NOT NULL)')
        self.module = legacy_module({7: {'id': 7, 'root': 'dram', 'status': 'done'}})
        reports.install(self.module, self.target)

    def target(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def drop(self):
        with psycopg.connect(self.dsn) as pg:
            pg.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_stages_reads_history_notes_and_run(self):
        rid, created = self.module.start('dram')
        self.assertTrue(created)
        self.assertGreaterEqual(rid, reports.ID_START)
        self.assertEqual(self.module.start('dram'), (rid, False))  # a running report is reused
        self.assertTrue(self.module.start('dram', 'top_down')[1])
        self.module._update(rid, progress='칸 메모 쓰는 중 (1/2)', tree_json='[{"key": "dram"}]')
        mid = self.module.read(rid)
        self.assertEqual((mid['status'], mid['progress'], mid['tree']), ('running', '칸 메모 쓰는 중 (1/2)', [{'key': 'dram'}]))
        self.module._update(rid, status='done', progress=None, body='보고서', refs_json='[]', missing_json='[]', finished_at='x')
        done = self.module.read(rid)
        self.assertEqual((done['status'], done['body'], done['outline'], done['missing']), ('done', '보고서', 'bottom_up', []))
        self.assertEqual(self.module.read(7)['status'], 'done')  # collected report
        self.assertIsNone(self.module.read(reports.ID_START + 999))
        self.assertEqual([r['id'] for r in self.module.history('dram')][-1], 7)
        self.assertEqual(len(self.module.history('dram', 2)), 2)
        with self.assertRaises(ValueError):
            self.module._update(rid, id=1)
        self.assertEqual(self.module._cached_note('dram', 'old'), 'collected note')
        self.module._store_note('dram', 'new', '새 메모')
        self.module._store_note('dram', 'new', '고친 메모')
        self.assertEqual(self.module._cached_note('dram', 'new'), '고친 메모')
        self.module._record('ok', 'root dram · 칸 2/2')
        with self.target() as pg:
            self.assertEqual(pg.execute("SELECT job,status FROM candidate_job_runs").fetchall(), [('chain_report', 'ok')])

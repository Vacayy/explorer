"""Collection target guard: live requires explicit opt-in and exact API schema."""
import os
import sqlite3
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import refactor_collect_trial as trial
import refactor_collect_scheduler as scheduler
import refactor_collect_engine as engine
import refactor_collect_job as job
import refactor_feed_recover as recover


class CollectionTargetTest(unittest.TestCase):
    def test_recovery_requires_one_matching_complete_queued_document(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'queue.sqlite')
            queue.enqueue('blog', 'source', RawDoc('blog', 'id', raw_content='body'))
            work = sqlite3.connect(':memory:')
            work.executescript('''
                CREATE TABLE raw_documents(id INTEGER,source_type TEXT,source_id TEXT,raw_content TEXT,markdown TEXT,content_hash TEXT);
                CREATE TABLE enrichments(id INTEGER,doc_id INTEGER,content_hash TEXT,summary TEXT);
                CREATE TABLE entities(id INTEGER); CREATE TABLE entity_keywords(id INTEGER); CREATE TABLE entity_relations(id INTEGER);
                CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                INSERT INTO candidate_publish_floor VALUES ('document_floor',0),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                INSERT INTO raw_documents VALUES (1,'blog','id','body','body','hash');
                INSERT INTO enrichments VALUES (1,1,'hash','summary');
            ''')
            seq, _, _ = recover.validate(work, queue)
            self.assertEqual(seq, queue.next()[0])
            work.execute("UPDATE enrichments SET content_hash='wrong'")
            with self.assertRaises(ValueError):
                recover.validate(work, queue)
            work.execute("UPDATE enrichments SET content_hash='hash'")
            work.execute("UPDATE candidate_publish_floor SET value=1 WHERE name='document_floor'")
            with self.assertRaises(ValueError):
                recover.validate(work, queue)
            recover.validate(work, queue, receipt_exists=True)
            queue.close()
            work.close()
    def test_model_budget_counts_primary_and_fallback_engine_attempts(self):
        from pipeline import llm
        from pipeline.llm_policies import resolve
        attempts = []

        def primary(*args, **kwargs):
            attempts.append('primary')
            raise RuntimeError('simulated primary failure')

        def fallback(*args, **kwargs):
            attempts.append('fallback')
            return llm.LLMResult(text='ok', model='test', engine='codex-exec')

        with patch.object(llm, '_run_claude_code', primary), patch.object(llm, '_run_codex', fallback), \
             patch.object(llm, '_run_api'), patch.object(llm, 'call_observer', None):
            refused = job._cap_table_model_calls(3)
            policy = resolve('document.tag', engine='claude-code', environ={})
            llm._execute('sample', policy=policy, record_call=lambda *_: None)
            with self.assertRaises(trial.Aborted):
                llm._execute('sample', policy=policy, record_call=lambda *_: None)
            self.assertEqual(attempts, ['primary', 'fallback', 'primary'])
            self.assertTrue(refused)

    def test_scheduled_compute_budget_counts_fallback_attempt(self):
        from pipeline import llm, postgres_scheduled_compute as compute
        from pipeline.llm_policies import resolve
        attempts = []

        def primary(*args, **kwargs):
            attempts.append('primary')
            raise RuntimeError('simulated primary failure')

        def fallback(*args, **kwargs):
            attempts.append('fallback')
            return llm.LLMResult(text='ok', model='test', engine='codex-exec')

        with patch.object(llm, '_run_claude_code', primary), patch.object(llm, '_run_codex', fallback), \
             patch.object(llm, '_run_api'), patch.object(llm, 'call_observer', None):
            compute._cap_model_calls(1)
            policy = resolve('document.tag', engine='claude-code', environ={})
            with self.assertRaises(compute.ModelBudgetExceeded):
                llm._execute('sample', policy=policy, record_call=lambda *_: None)
            self.assertEqual(attempts, ['primary'])
    def test_minimal_feed_keeps_unpublished_documents_after_failure(self):
        from pipeline.base import RawDoc, SourceRef
        from pipeline.feed_backlog import FeedBacklog

        class Connector:
            def discover(self):
                return [SourceRef('feed')]

            def discover_posts(self, _ref):
                return [SourceRef('first'), SourceRef('second')]

            def fetch_post(self, ref):
                return RawDoc('blog', ref.key)

        with TemporaryDirectory() as directory, patch.object(job, '_blog_document_known', return_value=False):
            path = Path(directory) / 'backlog.sqlite'
            with patch.object(trial, 'run_documents', side_effect=RuntimeError('simulated publication failure')):
                with self.assertRaises(RuntimeError):
                    job.run_minimal_blog(None, Connector(), queue_path=path)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 1)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 1)
            queue.close()
            result = {'counts': {'new': 1}, 'stats': {}, 'published': 1}
            with patch.object(trial, 'run_documents', return_value=result):
                job.run_minimal_blog(None, Connector(), queue_path=path)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 0)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 1)
            queue.close()
    def test_media_is_readonly_and_feed_only(self):
        def spec(label, mount):
            return {'Image': engine.IMAGE, 'Labels': {engine.LABEL: '1', engine.LABEL + '.job': label},
                    'HostConfig': {'Binds': [mount], 'CapDrop': ['ALL'], 'NetworkMode': engine.NETWORK}}
        engine.check(spec('chain', 'explorer-refactor-media:/app/media:ro'))
        with self.assertRaises(ValueError):
            engine.check(spec('chain', 'explorer-refactor-media:/app/media'))
        with self.assertRaises(ValueError):
            engine.check(spec('prices', 'explorer-refactor-media:/app/media:ro'))

    def test_all_catchup_waits_until_priority_slot(self):
        with patch.dict(os.environ, {'COLLECT_CATCHUP_AFTER': '2026-11-17T22:10:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'history'}, datetime(2026, 11, 17, 22, 9, tzinfo=timezone.utc)), set())
            self.assertEqual(scheduler.catchup_enabled({'history'}, datetime(2026, 11, 17, 22, 10, tzinfo=timezone.utc)), {'history'})

    def test_work_volume_must_be_the_collection_volume(self):
        with patch.dict(os.environ, {'COLLECT_WORK_VOLUME': 'explorer-refactor-collect-recovery-20261118a'}):
            self.assertEqual(engine.work_volume(), 'explorer-refactor-collect-recovery-20261118a')
        with patch.dict(os.environ, {'COLLECT_WORK_VOLUME': 'explorer-refactor-media'}):
            with self.assertRaises(ValueError):
                engine.work_volume()

    def test_feed_work_volume_is_explicit_and_restricted(self):
        with patch.dict(os.environ, {'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test'}):
            self.assertEqual(engine.feed_work_volume(), 'explorer-refactor-collect-feed-test')
        with patch.dict(os.environ, {'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-media'}):
            with self.assertRaises(ValueError):
                engine.feed_work_volume()

    def test_feed_failure_does_not_hold_other_jobs(self):
        with TemporaryDirectory() as directory, \
             patch.object(scheduler, 'HOLD', Path(directory) / 'global'), \
             patch.object(scheduler, 'FEED_HOLD', Path(directory) / 'feed'), \
             patch.dict(os.environ, {'COLLECT_CHAIN_INTAKE_ONLY': '1', 'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test'}), \
             patch.object(scheduler, '_run_one', return_value=False):
            self.assertFalse(scheduler.run_job('chain', lambda *_: None))
            self.assertTrue(scheduler.FEED_HOLD.exists())
            self.assertFalse(scheduler.HOLD.exists())

    def test_us_briefing_requires_synthesis(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE job_runs(id INTEGER, job TEXT, summary TEXT, ran_at TEXT)')
        conn.execute('INSERT INTO job_runs VALUES (1,?,?,?)', ('compute_briefing', 'status ok · synthesis False', '2026-11-18 00:00:00'))
        with self.assertRaises(trial.HeldBack):
            job.require_us_briefing_synthesis(conn, '2026-11-18 00:00:00')
        conn.execute('UPDATE job_runs SET summary=?', ('status ok · synthesis True',))
        job.require_us_briefing_synthesis(conn, '2026-11-18 00:00:00')
        conn.close()

    def test_send_secrets_require_explicit_key_selection(self):
        with TemporaryDirectory() as directory:
            secret_file = Path(directory) / 'secrets'
            secret_file.write_text('DART_API_KEY=test\nTELEGRAM_BOT_TOKEN=test\nTELEGRAM_CHAT_ID=test\n')
            secret_file.chmod(0o600)
            with patch.object(engine, 'SECRETS_FILE', secret_file):
                self.assertEqual(set(engine.secrets()), {'DART_API_KEY'})
                self.assertEqual(set(engine.secrets(engine.SECRET_KEYS + engine.SEND_KEYS)),
                                 {'DART_API_KEY', *engine.SEND_KEYS})

    def test_only_connected_send_can_be_enabled(self):
        scheduler.check_enabled({'briefing', 'observeweekly', 'observealerts', 'pfintraday'})
        with self.assertRaises(SystemExit):
            scheduler.check_enabled({'pfclose'})

    def test_observation_alert_waits_for_configured_slot(self):
        with patch.dict(os.environ, {'COLLECT_OBSERVE_ALERTS_AFTER': '2026-11-18T01:00:00+09:00'}):
            jobs = [('observealerts', [], 3600)]
            before = datetime.fromisoformat('2026-11-18T00:59:00+09:00')
            after = datetime.fromisoformat('2026-11-18T01:00:00+09:00')
            intervals = {}
            self.assertEqual(scheduler.due_now(jobs, {'observealerts'}, before, before, intervals), [])
            self.assertEqual(scheduler.due_now(jobs, {'observealerts'}, before, after, intervals), ['observealerts'])

    def test_price_catchup_waits_for_the_next_slot(self):
        with patch.dict(os.environ, {'COLLECT_PRICES_CATCHUP_AFTER': '2026-11-18T07:35:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 34, tzinfo=timezone.utc)), {'watch'})
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 35, tzinfo=timezone.utc)), {'prices', 'watch'})

    def test_us_briefing_catchup_waits_for_market_close_slot(self):
        with patch.dict(os.environ, {'COLLECT_USBRIEFING_CATCHUP_AFTER': '2026-11-17T21:30:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'usbriefing'}, datetime(2026, 11, 17, 21, 29, tzinfo=timezone.utc)), set())
            self.assertEqual(scheduler.catchup_enabled({'usbriefing'}, datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)), {'usbriefing'})

    def test_source_stop_is_not_swallowed_by_library_retry(self):
        def retrying_client():
            try:
                raise trial.Aborted('request cap')
            except Exception:
                return 'retry'

        with self.assertRaises(trial.Aborted):
            retrying_client()

    def test_chain_intake_only_runs_one_step(self):
        with TemporaryDirectory() as directory, patch.object(scheduler, 'HOLD', Path(directory) / 'hold'), \
             patch.dict(os.environ, {'COLLECT_CHAIN_INTAKE_ONLY': '1'}), \
             patch.object(scheduler, '_run_one', return_value=True) as run:
            self.assertTrue(scheduler.run_job('chain', lambda *_: None))
            self.assertEqual([args[0][0] for args in run.call_args_list], ['chain'])

    def test_target_guard(self):
        live = 'refactor_fixture_' + 'a' * 32
        clone = 'refactor_fixture_' + 'b' * 32
        driver = types.SimpleNamespace(connect=lambda *args, **kwargs: 'connected')
        for mode, schema, allowed in [('', live, False), ('', clone, True),
                                      ('live', live, True), ('live', clone, False),
                                      ('live', 'invalid', False)]:
            with self.subTest(mode=mode, allowed=allowed), patch.dict(os.environ, {
                'REFACTOR_POSTGRES_DSN': 'test', 'TRIAL_LIVE_SCHEMA': live,
                'REFACTOR_FIXTURE_SCHEMA': schema, 'COLLECT_TARGET': mode,
            }), patch.dict(sys.modules, {'psycopg': driver}):
                if allowed:
                    self.assertEqual(trial._pg(), 'connected')
                else:
                    with self.assertRaises(ValueError):
                        trial._pg()

    def test_scheduler_holds_on_failure_and_after_interruption(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / 'hold'
            with patch.object(scheduler, 'HOLD', marker):
                with patch.object(scheduler, '_run_one', return_value=True):
                    self.assertTrue(scheduler.run_job('prices', lambda *_: None))
                    self.assertFalse(marker.exists())
                with patch.object(scheduler, '_run_one', return_value=False):
                    self.assertFalse(scheduler.run_job('prices', lambda *_: None))
                    self.assertTrue(marker.exists())
                with patch.object(scheduler, '_run_one') as run:
                    self.assertFalse(scheduler.run_job('watch', lambda *_: None))
                    run.assert_not_called()
                marker.unlink()
                with patch.object(scheduler, '_run_one', side_effect=RuntimeError('interrupted')):
                    with self.assertRaises(RuntimeError):
                        scheduler.run_job('prices', lambda *_: None)
                    self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()

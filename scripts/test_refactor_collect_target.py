"""Collection target guard: live requires explicit opt-in and exact API schema."""
import os
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


class CollectionTargetTest(unittest.TestCase):
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
        scheduler.check_enabled({'briefing', 'observeweekly'})
        with self.assertRaises(SystemExit):
            scheduler.check_enabled({'pfclose'})

    def test_price_catchup_waits_for_the_next_slot(self):
        with patch.dict(os.environ, {'COLLECT_PRICES_CATCHUP_AFTER': '2026-11-18T07:35:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 34, tzinfo=timezone.utc)), {'watch'})
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 35, tzinfo=timezone.utc)), {'prices', 'watch'})

    def test_source_stop_is_not_swallowed_by_library_retry(self):
        def retrying_client():
            try:
                raise trial.Aborted('request cap')
            except Exception:
                return 'retry'

        with self.assertRaises(trial.Aborted):
            retrying_client()

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

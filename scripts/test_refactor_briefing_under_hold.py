"""The briefing-under-hold procedure without PG or launchd: verdicts and the hold always put back."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import refactor_briefing_under_hold as rescue


def _found(**changed):
    found = {t: {'work_only': 0, 'pg_only': 0} for t in rescue.BRIEFING_TABLES}
    for table, counts in changed.items():
        found[table].update(counts)
    return found


class VerdictTest(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(rescue.verdict(_found(), [])[0], 'safe')
        self.assertNotIn('job_runs', rescue.BRIEFING_TABLES)  # published by id: other runs' records never go out
        self.assertEqual(rescue.verdict(_found(market_indicators={'work_only': 3}), [])[0], 'stop')
        self.assertEqual(rescue.verdict(_found(us_movers={'pg_only': 1}), [])[0], 'stop')


class RunTest(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        (self.state / 'logs').mkdir()
        self.hold = self.state / 'collect-scheduler.hold'
        self.hold.write_text('extseries 2026-11-21 21:00:00 UTC\n')
        self.calls = []
        patcher = mock.patch.multiple(rescue, STATE=self.state, PLIST=self.state / 'x.plist')
        patcher.start()
        self.addCleanup(patcher.stop)
        run = mock.patch.object(rescue.subprocess, 'run', side_effect=lambda argv, **_: self.calls.append(argv[1]))
        run.start()
        self.addCleanup(run.stop)

    def test_success_restores_hold_then_restarts(self):
        def runner(_log):
            self.assertFalse(self.hold.exists())  # moved aside while the briefing runs
            return 0
        self.assertEqual(rescue.run(runner), 0)
        self.assertEqual(self.hold.read_text(), 'extseries 2026-11-21 21:00:00 UTC\n')
        self.assertEqual(self.calls, ['bootout', 'bootstrap'])

    def test_failed_run_keeps_its_marker_and_restores_the_hold(self):
        def runner(_log):
            self.hold.write_text('usbriefing 2026-11-21 21:30:00 UTC\n')  # the failed run's own hold marker
            return 1
        self.assertEqual(rescue.run(runner), 1)
        self.assertEqual(self.hold.read_text(), 'extseries 2026-11-21 21:00:00 UTC\n')
        self.assertEqual(len(list(self.state.glob('collect-scheduler.hold-usbriefing-failed-*'))), 1)
        self.assertEqual(self.calls, ['bootout', 'bootstrap'])

    def test_crashing_run_restores_the_hold_and_does_not_restart(self):
        def runner(_log):
            raise RuntimeError('docker gone')
        with self.assertRaises(RuntimeError):
            rescue.run(runner)
        self.assertEqual(self.hold.read_text(), 'extseries 2026-11-21 21:00:00 UTC\n')
        self.assertEqual(self.calls, ['bootout'])  # left stopped: the operator looks first

    def test_hold_not_back_leaves_scheduler_stopped(self):
        def runner(_log):
            return 0
        real_replace = rescue.os.replace

        def lose_restore(src, dst):
            if Path(dst) == self.hold:
                return None  # the hold cannot be put back
            return real_replace(src, dst)
        with mock.patch.object(rescue.os, 'replace', side_effect=lose_restore), self.assertRaises(SystemExit):
            rescue.run(runner)
        self.assertEqual(self.calls, ['bootout'])


if __name__ == '__main__':
    unittest.main()

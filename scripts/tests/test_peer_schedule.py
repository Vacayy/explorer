import contextlib
import io
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_launchd


class PeerScheduleTests(unittest.TestCase):
    def test_only_peer_preview_does_not_call_launchctl(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(install_launchd, 'AGENTS', Path(directory)), patch.object(install_launchd, '_run') as run, patch.object(sys, 'argv', ['install_launchd', '--only', 'peer', '--dry-run']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(install_launchd.main(), 0)
            run.assert_not_called()
            self.assertEqual(output.getvalue().count('<?xml'), 1)
            plist = plistlib.loads(output.getvalue()[output.getvalue().index('<?xml'):].encode())
            self.assertEqual(plist['Label'], 'dev.explorer.peer')
            self.assertEqual(plist['ProgramArguments'][-1], 'peer')
            self.assertEqual(plist['StartCalendarInterval'], [{'Weekday': day, 'Hour': 20, 'Minute': 30} for day in range(1, 6)])

    def test_only_peer_uninstall_does_not_touch_other_jobs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(install_launchd, 'AGENTS', Path(directory)), patch.object(install_launchd, '_run') as run, patch.object(sys, 'argv', ['install_launchd', '--only', 'peer', '--uninstall']):
            other = Path(directory) / 'dev.explorer.prices.plist'
            other.write_text('preserve')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(install_launchd.main(), 0)
            self.assertEqual(other.read_text(), 'preserve')
            self.assertEqual(run.call_count, 1)
            self.assertTrue(run.call_args.args[-1].endswith('/dev.explorer.peer'))

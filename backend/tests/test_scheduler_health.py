"""Scheduler health must not report unavailable inspection as success."""
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from pipeline import health


class SchedulerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "scheduler-health.json"
        self.now = datetime(2026, 11, 14, 11, tzinfo=timezone.utc)
        self.enterContext(patch.object(health, "SCHEDULER_HEALTH", self.path))
        self.enterContext(patch.object(health.sys, "platform", "linux"))

    def write(self, **changes):
        data = {"state": "running", "utc": self.now.isoformat(), "jobs": 39, "active": 0}
        data.update(changes)
        self.path.write_text(json.dumps(data))

    def test_missing_or_corrupt_cannot_be_healthy(self):
        self.assertEqual(health.scheduler_item(self.now)["status"], "error")
        for value in ("{", "[]", "null"):
            self.path.write_text(value)
            self.assertEqual(health.scheduler_item(self.now)["status"], "error")

    def test_fresh_cross_container_heartbeat_does_not_inspect_pid(self):
        self.write(pid=99999999)
        item = health.scheduler_item(self.now)
        self.assertEqual(item["status"], "ok")
        self.assertIn("작업 성공", item["detail"])

    def test_expired_future_stopping_and_wrong_job_count(self):
        for changes in ({"utc": (self.now-timedelta(seconds=91)).isoformat()},
                        {"utc": (self.now+timedelta(seconds=1)).isoformat()},
                        {"state": "stopping"}, {"jobs": 0}):
            self.write(**changes)
            self.assertNotEqual(health.scheduler_item(self.now)["status"], "ok")

    def test_invalid_timestamp_is_not_a_server_error(self):
        for value in (None, "bad", "2026-11-14T11:00:00"):
            self.write(utc=value)
            self.assertEqual(health.scheduler_item(self.now)["status"], "error")

    def test_launchctl_failure_is_unknown_not_success(self):
        with patch.object(health.sys, "platform", "darwin"):
            for failure in (FileNotFoundError(), subprocess.CalledProcessError(1, "launchctl")):
                with patch.object(health.subprocess, "run", side_effect=failure):
                    self.assertEqual(health.scheduler_item(self.now)["status"], "error")

    def test_launchctl_empty_registration_is_not_healthy(self):
        with patch.object(health.sys, "platform", "darwin"), patch.object(
            health.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "PID\tStatus\tLabel\n")
        ):
            self.assertEqual(health.scheduler_item(self.now)["status"], "error")

    def test_launchctl_reports_failed_jobs(self):
        with patch.object(health.sys, "platform", "darwin"), patch.object(
            health.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "-\t1\tdev.explorer.chain\n")
        ):
            self.assertEqual(health.scheduler_item(self.now)["status"], "stale")

"""에이전트 제안 배치는 job_runs를 기록하기 전에 자기 쓰기를 커밋한다.

09-08 이후 proposals 잡은 vocab_merge 판정 실패를 기록하려다 자기 미커밋 트랜잭션에 막혀
'database is locked'로 죽었다. 앞 단계에서 만든 제안도 커밋되지 않아 사라졌다.
"""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import agent_proposals as ap
from pipeline import ops
from tests.test_job_status import KeepOpen


class RunAllCommitTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:")
        raw.execute("CREATE TABLE proposals(kind TEXT)")
        raw.commit()
        self.conn = KeepOpen(raw)
        self.open_at_record = []

    def scan(self, kind):
        def _scan(conn):
            conn.execute("INSERT INTO proposals VALUES (?)", (kind,))
            return 1
        return _scan

    def record(self, *args, **kwargs):
        self.open_at_record.append(self.conn.in_transaction)

    def test_failed_vocab_merge_is_recorded_and_earlier_proposals_survive(self):
        with patch.object(ap, "get_connection", return_value=self.conn), \
             patch.object(ap, "scan_neglect", side_effect=self.scan("neglect")), \
             patch.object(ap, "scan_contested_edges", side_effect=self.scan("contested")), \
             patch.object(ap, "scan_falsifier_watch", side_effect=self.scan("falsifier")), \
             patch.object(ap, "scan_report_suggestions", side_effect=self.scan("report")), \
             patch.object(ap, "scan_devils_advocate", side_effect=self.scan("devil")), \
             patch.object(ap, "scan_vocab_merges", side_effect=RuntimeError("claude -p 실패")), \
             patch.object(ops, "flag_enabled", return_value=True), \
             patch.object(ops, "record_run", side_effect=self.record):
            stats = ap.run_all(include_llm=True)
        self.assertEqual(stats["vocab_merge"], "error: RuntimeError")
        self.assertEqual(self.open_at_record, [False], "job_runs 기록 시점에 쓰기 트랜잭션이 열려 있었다")
        kinds = {r[0] for r in self.conn.execute("SELECT kind FROM proposals")}
        self.assertEqual(kinds, {"neglect", "contested", "falsifier", "report", "devil"})


if __name__ == "__main__":
    unittest.main()

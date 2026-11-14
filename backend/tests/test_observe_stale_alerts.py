"""데이터 신선도 멈춤을 즉시 경고에 올린다 — 2026-11-06 수집 체인 45시간 정지가 경고 없이 지나갔다."""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import health, observe


def item(key, status, critical=False, detail=''):
    return {"key": key, "label": key.upper(), "status": status, "critical": critical, "detail": detail}


class StaleAlertTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript("""
            CREATE TABLE job_runs(id INTEGER PRIMARY KEY, job TEXT, status TEXT, summary TEXT, duration_ms INT, ran_at TEXT);
            CREATE TABLE llm_calls(cost_usd REAL, created_at TEXT, job TEXT);
            CREATE TABLE api_requests_hourly(hour TEXT, count INT, status_class TEXT);
        """)

    def conditions(self, items):
        with patch.object(health, 'report', return_value=items):
            return observe._conditions(self.conn)

    def test_critical_chain_and_youtube_stalls_alert(self):
        out = self.conditions([item('documents', 'stale', True, '45시간 전'), item('chain', 'stale', False, '46시간 전'),
                               item('youtube', 'stale', False, '4.0일 전')])
        self.assertEqual(out['stale:documents'], 'DOCUMENTS 멈춤 — 45시간 전')
        self.assertIn('stale:chain', out)
        self.assertIn('stale:youtube', out)

    def test_other_non_critical_and_ok_items_stay_on_admin_screen(self):
        out = self.conditions([item('retail', 'stale', False, '1거래일 지연'), item('documents', 'ok', True)])
        self.assertFalse([k for k in out if k.startswith('stale:')])


if __name__ == '__main__':
    unittest.main()

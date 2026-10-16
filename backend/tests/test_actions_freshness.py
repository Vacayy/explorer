"""기업활동 신선도는 서버 현재 시각이 아니라 마지막 DART 스캔 성공 시각이다.

as_of에 datetime.now()를 넣어 화면이 늘 '방금 기준'이었다 — DART 장애로 스캔이 실패해도 티가 안 났다.
"""
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routers import spine_actions
from tests.test_job_status import KeepOpen


class ActionsFreshnessTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.executescript("""
            CREATE TABLE corporate_actions(id INTEGER PRIMARY KEY, rcp_no TEXT, corp_code TEXT, corp_name TEXT, stock_code TEXT,
                market TEXT, action_type TEXT, report_nm TEXT, rcept_dt TEXT, market_cap INT, created_at TEXT, summary TEXT);
            CREATE TABLE capital_raise_details(rcp_no TEXT, stock_code TEXT, action_type TEXT, date_disclosure TEXT);
            CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, close REAL);
            CREATE TABLE job_runs(job TEXT, status TEXT, ran_at TEXT);
            CREATE TABLE stock_groups(id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
            CREATE TABLE stock_group_members(group_id INT, stock_code TEXT);
            INSERT INTO job_runs VALUES ('scan_actions', 'ok', '2026-10-16 03:26:26'),
                                        ('scan_actions', 'error', '2026-10-16 04:39:17');
        """)
        self.conn = KeepOpen(raw)
        self.client = TestClient(app)

    def get(self, path):
        with patch.object(spine_actions, "get_connection", return_value=self.conn):
            return self.client.get(path).json()

    def test_as_of_is_the_last_successful_scan(self):
        self.assertEqual(self.get("/api/spine/actions")["as_of"], "2026-10-16T03:26:26Z")
        self.assertEqual(self.get("/api/spine/actions/rights")["as_of"], "2026-10-16T03:26:26Z")

    def test_no_successful_scan_is_null(self):
        self.conn.execute("DELETE FROM job_runs WHERE status='ok'")
        self.assertIsNone(self.get("/api/spine/actions")["as_of"])


if __name__ == "__main__":
    unittest.main()

"""기업활동 목록 — 정정 공시를 원공시와 가르고, 내 묶음(보유·관심) 종목을 표시한다 (조사 D: 목록의 38%가 정정)."""
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routers import spine_actions
from tests.test_job_status import KeepOpen

TODAY = date.today().strftime("%Y%m%d")


class ActionsFilterTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.executescript("""
            CREATE TABLE corporate_actions(id INTEGER PRIMARY KEY, rcp_no TEXT, corp_code TEXT, corp_name TEXT, stock_code TEXT,
                market TEXT, action_type TEXT, report_nm TEXT, rcept_dt TEXT, market_cap INT, created_at TEXT, summary TEXT);
            CREATE TABLE job_runs(job TEXT, status TEXT, ran_at TEXT);
            CREATE TABLE stock_groups(id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
            CREATE TABLE stock_group_members(group_id INT, stock_code TEXT);
            INSERT INTO stock_groups VALUES (1, '관심 종목', 'watch'), (4, '내 포트폴리오', 'portfolio');
            -- 000660은 관심이면서 보유 → 보유가 이긴다
            INSERT INTO stock_group_members VALUES (1, '005930'), (1, '000660'), (4, '000660');
        """)
        raw.executemany("INSERT INTO corporate_actions(rcp_no, corp_name, stock_code, action_type, report_nm, rcept_dt) VALUES (?,?,?,?,?,?)", [
            ("1", "삼성전자", "005930", "유상증자", "주요사항보고서(유상증자결정)", TODAY),
            ("2", "삼성전자", "005930", "유상증자", "[기재정정]주요사항보고서(유상증자결정)", TODAY),
            ("3", "SK하이닉스", "000660", "합병", "[첨부정정]주요사항보고서(회사합병결정)", TODAY),
            ("4", "카카오", "035720", "합병", "주요사항보고서(회사합병결정)", TODAY),
        ])
        self.conn = KeepOpen(raw)
        self.client = TestClient(app)

    def get(self, path):
        with patch.object(spine_actions, "get_connection", return_value=self.conn):
            return self.client.get(path).json()

    def test_counts_and_original_filter(self):
        d = self.get("/api/spine/actions?kind=original")
        self.assertEqual(d["counts"], {"original": 2, "correction": 2})
        self.assertEqual({a["rcp_no"] for a in d["items"]}, {"1", "4"})
        self.assertTrue(all(not a["is_correction"] for a in d["items"]))

    def test_correction_filter_and_default_all(self):
        self.assertEqual({a["rcp_no"] for a in self.get("/api/spine/actions?kind=correction")["items"]}, {"2", "3"})
        self.assertEqual(self.get("/api/spine/actions")["total"], 4)

    def test_my_group_marks(self):
        by = {a["rcp_no"]: a["my_group"] for a in self.get("/api/spine/actions")["items"]}
        self.assertEqual(by, {"1": "관심", "2": "관심", "3": "보유", "4": None})

    def test_single_stock(self):
        d = self.get("/api/spine/actions?stock_code=005930")
        self.assertEqual(d["counts"], {"original": 1, "correction": 1})
        self.assertEqual(d["total"], 2)


if __name__ == "__main__":
    unittest.main()

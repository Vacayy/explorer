"""콜 상세 '다가오는 분기' — 가장 가까운 아직 안 한 발표·기대·발표일 기준 offset·최근 30일 목표가, 없으면 404."""
import json
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from models.earnings_chain import UpcomingChain
from pipeline import earnings_chain as ec
from tests.test_job_status import KeepOpen

SCHEMA = """
CREATE TABLE transcript_follow (ticker TEXT PRIMARY KEY, company_name TEXT, entity_id INTEGER, group_label TEXT, sic TEXT,
  market_cap REAL, fiscal_year_end TEXT, core_pinned INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE transcripts (id INTEGER PRIMARY KEY, raw_doc_id INTEGER, ticker TEXT, fiscal_year INTEGER, fiscal_period TEXT, call_date TEXT);
CREATE TABLE transcript_reactions (transcript_id INTEGER PRIMARY KEY, status TEXT, meta_json TEXT);
CREATE TABLE earnings_events (ticker TEXT, fiscal_year INTEGER, fiscal_period TEXT, event_date TEXT, season TEXT, confirmed INTEGER,
  PRIMARY KEY (ticker, fiscal_year, fiscal_period));
CREATE TABLE earnings_expectations (ticker TEXT, fiscal_year INTEGER, fiscal_period TEXT, snapshot TEXT, event_date TEXT, quant_json TEXT,
  issues_json TEXT, positioning TEXT, points_json TEXT, thin TEXT, n_docs INTEGER, prompt_version TEXT, input_hash TEXT, created_at TEXT,
  PRIMARY KEY (ticker, fiscal_year, fiscal_period, snapshot));
CREATE TABLE us_prices (stock_code TEXT, trade_date TEXT, close REAL, volume REAL);
CREATE TABLE us_pt_changes (ticker TEXT, graded_at TEXT, firm TEXT, action TEXT, to_grade TEXT, pt_from REAL, pt_to REAL, fetched_at TEXT);
"""
TODAY = date(2026, 11, 6)   # 금요일
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]


class UpcomingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)   # TestClient는 다른 스레드에서 부른다
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        c = self.conn
        c.execute("INSERT INTO transcript_follow VALUES ('CSCO','Cisco',NULL,'networking',NULL,1e11,'07-31',0,1)")
        # 지난 분기(녹취록 있음)·다가오는 분기(11/12, 예상일)·그다음 분기
        c.execute("INSERT INTO transcripts VALUES (1, 1, 'CSCO', 2026, 'Q4', '2026-08-13')")
        c.executemany("INSERT INTO earnings_events VALUES (?,?,?,?,?,?)", [
            ("CSCO", 2026, "Q4", "2026-08-13", "2026Q2", 1), ("CSCO", 2027, "Q1", "2026-11-12", "2026Q3", 0),
            ("CSCO", 2027, "Q2", "2027-02-11", "2026Q4", 0)])
        c.execute("INSERT INTO earnings_expectations (ticker, fiscal_year, fiscal_period, snapshot, event_date, quant_json, issues_json, points_json, created_at) "
                  "VALUES ('CSCO', 2027, 'Q1', 'd7', '2026-11-12', ?, ?, ?, '2026-11-04 22:20:00')",
                  (json.dumps({"eps_est": 1.0}), json.dumps([{"issue": "AI 주문", "good": "가이던스 상향", "bad": "주문 둔화", "weight": "high"}]),
                   json.dumps(["AI 주문이 관건"])))
        for code, px in (("CSCO", [100, 101, 102, 104]), ("SMH", [200, 200, 202, 202])):
            c.executemany("INSERT INTO us_prices VALUES (?,?,?,1000)", [(code, d, p) for d, p in zip(DAYS, px)])
        c.executemany("INSERT INTO us_pt_changes (ticker, graded_at, firm, pt_from, pt_to) VALUES (?,?,?,?,?)", [
            ("CSCO", "2026-10-20 00:00:00", "A", 80, 88), ("CSCO", "2026-09-01 00:00:00", "Old", 70, 60)])
        c.commit()
        self.patch = patch.object(ec, "get_connection", lambda: KeepOpen(self.conn))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_next_unreported_event_with_expectation(self):
        d = ec.upcoming_detail("CSCO", today=TODAY)
        UpcomingChain(**d)   # 응답 모델과 모양이 같다
        self.assertEqual((d["fiscal_year"], d["fiscal_period"], d["event_date"]), (2027, "Q1", "2026-11-12"))
        self.assertEqual((d["days_to_event"], d["confirmed"], d["etf"]), (6, False, "SMH"))
        self.assertEqual(d["expectation"]["issues"][0]["good"], "가이던스 상향")
        self.assertIsNone(d["reaction_meta"])

    def test_series_offsets_count_to_event_day(self):
        d = ec.upcoming_detail("CSCO", today=TODAY)
        # 최근 종가 11/5 → 11/12까지 평일 11/6·9·10·11 = 4 → offset -5. 기준(0%)은 최근 종가
        self.assertEqual([r["offset"] for r in d["series"]], [-8, -7, -6, -5])
        self.assertEqual(d["series"][-1]["ret"], 0)
        self.assertEqual(d["series"][0]["excess"], round((100 / 104 - 1) * 100 - (200 / 202 - 1) * 100, 2))

    def test_pt_changes_last_30_days_only(self):
        d = ec.upcoming_detail("CSCO", today=TODAY)
        self.assertEqual((d["pt_before"]["n"], d["pt_before"]["up"]), (1, 1))

    def test_history_lists_past_confirmed_quarters(self):
        d = ec.upcoming_detail("CSCO", today=TODAY)
        self.assertEqual([h["fiscal"] for h in d["history"]], ["FY2026 Q4"])

    def test_skips_quarter_whose_transcript_arrived(self):
        self.conn.execute("INSERT INTO transcripts VALUES (2, 2, 'CSCO', 2027, 'Q1', '2026-11-12')")
        d = ec.upcoming_detail("CSCO", today=TODAY)
        self.assertEqual(d["fiscal_period"], "Q2")
        self.assertIsNone(d["expectation"])

    def test_endpoint_404_without_upcoming_event(self):
        self.conn.execute("DELETE FROM earnings_events WHERE event_date >= '2026-11-06'")
        r = TestClient(app).get("/api/spine/transcript/chain/upcoming/csco")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()

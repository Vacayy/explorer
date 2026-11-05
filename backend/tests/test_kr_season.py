"""국내 실적 시즌 1단계 — 반응 창(2일·5일·당일·집계 중), 업종 대비(중앙값·표본 5 미만 비움), 시즌 묶음·아직 발표 전, 엔드포인트 (ia-redesign §4.22)."""
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from pipeline import kr_season as k
from tests.test_job_status import KeepOpen

DAYS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"]


class WindowTests(unittest.TestCase):
    def test_two_day_and_five_day_windows(self):
        w = k.window_days(DAYS, "2026-10-27")
        self.assertEqual(w, {"base": "2026-10-26", "d1": "2026-10-28", "d5": "2026-11-03", "same": "2026-10-27"})

    def test_weekend_filing_uses_friday_close_and_monday(self):
        w = k.window_days(DAYS, "2026-10-31")      # 토요일 공시
        self.assertEqual((w["base"], w["d1"], w["same"]), ("2026-10-30", "2026-11-02", None))

    def test_latest_day_filing_has_no_next_day_yet(self):
        w = k.window_days(DAYS, "2026-11-04")
        self.assertEqual((w["base"], w["d1"], w["d5"], w["same"]), ("2026-11-03", None, None, "2026-11-04"))

    def test_deadline_rolls_weekend_to_monday(self):
        self.assertEqual(k.deadline("2026Q3"), "2026-11-16")   # 9/30 + 45 = 11/14(토)
        self.assertEqual(k.deadline("2026Q2"), "2026-08-14")
        self.assertEqual(k.deadline("2026Q4"), "2027-03-31")


class ReactionTests(unittest.TestCase):
    def closes(self, code, prices):
        return {(code, d): p for d, p in zip(DAYS, prices)}

    def test_relative_is_minus_peer_median_and_blank_below_five(self):
        self.assertAlmostEqual(k.relative(5.0, [1, 2, 3, 4, 10]), 2.0)
        self.assertIsNone(k.relative(5.0, [1, 2, 3, 4]))
        self.assertIsNone(k.relative(None, [1, 2, 3, 4, 5]))

    def test_final_first_reaction_and_pending_five_day(self):
        c = self.closes("A", [100, 100, 110, 110, 110, 110, 110, 110])
        peers = []
        for i, p in enumerate([101, 102, 103, 104, 105]):       # 10/26 100 → 10/28 p: +1~+5%, 중앙값 +3%
            c.update(self.closes(f"P{i}", [100, 100, p, p, p, p, p, p]))
            peers.append(f"P{i}")
        w = k.window_days(DAYS[:6], "2026-10-27")             # 11/2까지만 시세 → 5거래일 차지 않음
        r = k.reaction(c, "A", w, peers)
        self.assertAlmostEqual(r["r1"], 10.0)
        self.assertAlmostEqual(r["x1"], 7.0)
        self.assertEqual(r["r1_state"], "final")
        self.assertEqual((r["r5"], r["x5"], r["r5_state"]), (None, None, "pending"))

    def test_same_day_reaction_when_next_day_missing(self):
        c = self.closes("A", [100] * 7 + [95])
        r = k.reaction(c, "A", k.window_days(DAYS, "2026-11-04"), ["X"])
        self.assertAlmostEqual(r["r1"], -5.0)
        self.assertEqual(r["r1_state"], "same_day")
        self.assertIsNone(r["x1"])                              # 업종 표본 1개 → 비움

    def test_missing_price_is_none_not_zero(self):
        r = k.reaction({}, "A", k.window_days(DAYS, "2026-10-27"), [])
        self.assertEqual((r["r1"], r["r1_state"], r["r5"], r["r5_state"]), (None, None, None, None))

    def test_group_rows_count_only_final_reactions(self):
        anns = [{"group": "금융", "r1": 2.0, "x1": 1.0, "r1_state": "final"},
                {"group": "금융", "r1": -4.0, "x1": -1.0, "r1_state": "final"},
                {"group": "금융", "r1": 9.0, "x1": 9.0, "r1_state": "same_day"},
                {"group": None, "r1": 1.0, "x1": 1.0, "r1_state": "final"}]
        g = k.group_rows(anns)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["n"], g[0]["median_r1"], g[0]["up_n"], g[0]["base_n"], g[0]["up_ratio"]), (3, -1.0, 1, 2, 50.0))


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)   # 동기 엔드포인트는 스레드 풀에서 돈다
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE disclosures(rcp_no TEXT PRIMARY KEY, corp_code TEXT, corp_name TEXT, report_nm TEXT, rcept_dt TEXT);
            CREATE TABLE companies(corp_code TEXT, corp_name TEXT, stock_code TEXT, sector TEXT);
            CREATE TABLE sector_map(sector_name TEXT, group_name TEXT);
            CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, close REAL, market_cap REAL);
        """)
        self.conn.execute("INSERT INTO sector_map VALUES ('은행', '금융')")
        corps = [("C1", "가은행", "000001"), ("C2", "나은행", "000002"), ("C3", "다은행", "000003")] + \
            [(f"P{i}", f"피어{i}", f"10000{i}") for i in range(5)]
        self.conn.executemany("INSERT INTO companies VALUES (?,?,?,'은행')", corps)
        for _, _, code in corps:
            for d in DAYS:
                self.conn.execute("INSERT INTO stock_prices VALUES (?,?,?,?)", (code, d, 120 if code == "000001" and d >= "2026-10-28" else 100, 2e12))
        self.conn.executemany("INSERT INTO disclosures VALUES (?,?,?,?,?)", [
            ("r1", "C1", "가은행", "연결재무제표기준영업(잠정)실적(공정공시)", "20261027"),
            ("r1b", "C1", "가은행", "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)", "20261028"),
            ("r2", "C2", "나은행", "영업(잠정)실적(공정공시)(자회사의 주요경영사항)", "20261029"),
            ("r3", "C1", "가은행", "영업(잠정)실적(공정공시)", "20260805"),
            ("r4", "C3", "다은행", "영업(잠정)실적(공정공시)", "20260806"),
            ("r5", "C2", "나은행", "결산실적공시예고", "20261030"),
        ])
        self._patches = [patch.object(k, "get_connection", return_value=KeepOpen(self.conn)),
                         patch.object(k, "backfilled", return_value=False),
                         patch.object(k, "MARKET_DAY_MIN", 1)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_overview_groups_first_prelim_per_corp_and_pending(self):
        o = k.overview(None, date(2026, 11, 5))
        self.assertEqual(o["season"]["key"], "2026Q3")
        self.assertEqual(o["deadline"], "2026-11-16")
        a = o["announcements"]
        self.assertEqual([(x["corp_code"], x["rcept_dt"], x["basis"]) for x in a], [("C1", "2026-10-27", "연결")])   # 정정·자회사·예고 제외
        self.assertAlmostEqual(a[0]["r1"], 20.0)
        self.assertAlmostEqual(a[0]["x1"], 20.0)            # 피어 5곳(자신 제외) 0% 중앙값
        self.assertEqual(a[0]["r1_state"], "final")
        self.assertAlmostEqual(a[0]["r5"], 20.0)
        self.assertEqual(a[0]["r5_state"], "final")
        self.assertIsNone(a[0]["figures"])
        self.assertEqual(o["kpi"]["reported"], 1)
        self.assertEqual(o["kpi"]["prev_reported"], 2)
        self.assertEqual(o["kpi"]["outperform_ratio"], 100.0)
        self.assertEqual([p["corp_code"] for p in o["pending"]], ["C3"])
        self.assertEqual(o["pending"][0]["prev_date"], "2026-08-06")
        self.assertEqual([s["key"] for s in o["seasons"]], ["2026Q2", "2026Q3"])
        self.assertEqual(o["calendar"], [{"date": "2026-10-27", "total": 1}])

    def test_past_season_has_no_week_or_changes(self):
        o = k.overview("2026Q2", date(2026, 11, 5))
        self.assertFalse(o["season"]["is_current"])
        self.assertIsNone(o["kpi"]["week"])
        self.assertEqual(o["changes"]["added"], [])
        self.assertEqual({x["corp_code"] for x in o["announcements"]}, {"C1", "C3"})

    def test_endpoint_shape_and_season_validation(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        with patch.object(k, "kst_today", return_value=date(2026, 11, 5)):
            r = client.get("/api/spine/transcript/season/kr")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["announcements"][0]["stock_code"], "000001")
        self.assertEqual(d["coverage"]["partial"], False)
        self.assertEqual(client.get("/api/spine/transcript/season/kr?season=2026-3").status_code, 422)


if __name__ == "__main__":
    unittest.main()

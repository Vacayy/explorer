"""홈 시장 탭 ① 지수 차트·요약 지표 (ia-redesign §4.2·4.3, D-325) — 장중 경로 수집과 overview API."""
import sqlite3
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from pipeline import index_intraday as ii
from pipeline import market_overview as mo
from pipeline import retail_heat as rh
from routers import spine_market_overview

KST_0930 = datetime(2026, 11, 6, 0, 30, tzinfo=timezone.utc)      # 11/6(금) 09:30 KST = 11/5 19:30 ET
KST_0830 = datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc) - timedelta(days=1)   # 11/6 08:30 KST(개장 전)


class _Conn(sqlite3.Connection):
    def close(self):   # 테스트 DB는 메모리 — 모듈이 닫아도 유지
        pass


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False, factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.executescript(ii.SCHEMA + rh.SCHEMA + """
        CREATE TABLE market_indicators (snapshot_date TEXT, indicator TEXT, value REAL, extra_json TEXT, fetched_at TEXT,
                                        PRIMARY KEY (snapshot_date, indicator));
        CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, close INTEGER);
        CREATE TABLE market_today (trade_date TEXT, slot TEXT, market_json TEXT);
    """)
    return conn


def _daily(conn, indicator, end, values):
    """end(포함)까지 평일마다 values를 거꾸로 채운다 — 마지막 값이 end."""
    d = date.fromisoformat(end)
    for v in reversed(values):
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        conn.execute("INSERT INTO market_indicators(snapshot_date, indicator, value) VALUES (?,?,?)", (d.isoformat(), indicator, v))
        d -= timedelta(days=1)


class IndexIntradayTests(unittest.TestCase):
    def test_due_markets_follow_local_sessions(self):
        self.assertEqual(ii.due_markets(KST_0930), ["kr"])
        self.assertEqual(ii.due_markets(datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)), ["us"])   # 10:00 ET
        self.assertEqual(ii.due_markets(datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)), [])        # 토요일
        self.assertEqual(ii.due_markets(datetime(2026, 11, 6, 6, 45, tzinfo=timezone.utc)), ["kr"])    # 15:45 마감+여유
        self.assertEqual(ii.due_markets(datetime(2026, 11, 6, 7, 0, tzinfo=timezone.utc)), [])

    def test_store_is_idempotent_and_seed_does_not_overwrite(self):
        conn = _db()
        rows = [("2026-11-05", "09:00", 100.0), ("2026-11-05", "09:05", 101.0)]
        self.assertEqual(ii.store(conn, "kr", "kospi", rows), 2)
        ii.store(conn, "kr", "kospi", [("2026-11-05", "09:05", 102.0)])      # 늦게 들어온 봉이 고친다
        conn.execute("INSERT INTO market_today VALUES ('2026-11-05', '1500', ?)",
                     ('{"path": [["09:05", 1.0], ["09:10", 103.0], ["16:10", 9.0]]}',))
        ii.seed_from_market_today(conn)
        got = conn.execute("SELECT hhmm, value FROM index_intraday ORDER BY hhmm").fetchall()
        self.assertEqual([tuple(r) for r in got], [("09:00", 100.0), ("09:05", 102.0), ("09:10", 103.0)])

    def test_collect_outside_session_makes_no_external_call(self):
        with patch.object(ii, "_bars") as bars:
            self.assertEqual(ii.collect([])["status"], "skipped")
            bars.assert_not_called()

    def test_collect_reports_holiday_as_skipped_and_errors_as_error(self):
        conn = _db()
        with patch.object(ii, "get_connection", return_value=conn):
            with patch.object(ii, "_bars", return_value=[]):
                self.assertEqual(ii.collect(["kr"])["status"], "skipped")
            with patch.object(ii, "_bars", side_effect=TimeoutError):
                self.assertEqual(ii.collect(["kr"])["status"], "error")
            with patch.object(ii, "_bars", return_value=[("2026-11-06", "09:00", 5000.0)]):
                r = ii.collect(["kr"])
        self.assertEqual((r["status"], r["indices"]), ("ok", ["kospi", "kosdaq"]))


class MarketOverviewTests(unittest.TestCase):
    def setUp(self):
        mo._breadth_memo = None
        self.conn = _db()
        _daily(self.conn, "index_kospi", "2026-11-05", [4000 + i for i in range(300)])   # 2026-11-05까지 평일 300개
        self.last_day = self.conn.execute("SELECT MAX(snapshot_date) FROM market_indicators").fetchone()[0]

    def test_open_session_uses_latest_bar_and_stored_prev_close(self):
        today = "2026-11-06"
        ii.store(self.conn, "kr", "kospi", [(today, "09:00", 4400.0), (today, "09:25", 4380.0)])
        k = mo.overview(self.conn, "kr", KST_0930)["indices"][0]
        prev = self.conn.execute("SELECT value FROM market_indicators WHERE snapshot_date=?", (self.last_day,)).fetchone()[0]
        self.assertEqual(k["session"]["state"], "open")
        self.assertEqual((k["value"], k["prev_close"]), (4380.0, prev))
        self.assertAlmostEqual(k["change_pct"], round((4380 / prev - 1) * 100, 2))
        d1 = k["ranges"][0]
        self.assertEqual([p["t"] for p in d1["points"]], ["09:00", "09:25"])   # 장중엔 지금까지만
        m1 = next(r for r in k["ranges"] if r["key"] == "1m")
        self.assertEqual((len(m1["points"]), m1["points"][-1]), (21, {"t": today, "v": 4380.0}))   # 기간 끝 = 지금 값

    def test_closed_day_appends_stored_close_at_session_end(self):
        ii.store(self.conn, "kr", "kospi", [(self.last_day, "09:00", 4250.0), (self.last_day, "14:55", 4290.0)])
        k = mo.overview(self.conn, "kr", KST_0830 + timedelta(hours=9))["indices"][0]   # 11/6 17:30 KST — 오늘 봉 없음(휴장)
        self.assertEqual(k["session"]["state"], "closed")
        self.assertEqual(k["ranges"][0]["points"][-1], {"t": "15:30", "v": 4299.0})
        self.assertEqual((k["value"], k["session"]["last_time"]), (4299.0, "15:30"))

    def test_before_open_shows_previous_day(self):
        ii.store(self.conn, "kr", "kospi", [(self.last_day, "09:00", 4250.0)])
        k = mo.overview(self.conn, "kr", KST_0830)["indices"][0]
        self.assertEqual((k["session"]["state"], k["session"]["trade_date"]), ("pre", self.last_day))

    def test_us_session_times_are_local_with_kst_label(self):
        _daily(self.conn, "index_sp500", "2026-11-05", [7000 + i for i in range(26)])
        sp_day = self.conn.execute("SELECT MAX(snapshot_date) FROM market_indicators WHERE indicator='index_sp500'").fetchone()[0]
        ii.store(self.conn, "us", "sp500", [(sp_day, "09:30", 7010.0)])
        sp = mo.overview(self.conn, "us", datetime.fromisoformat(f"{sp_day}T23:00:00+00:00"))["indices"][0]
        self.assertEqual((sp["session"]["state"], sp["session"]["last_time"]), ("closed", "16:00"))
        self.assertEqual(sp["session"]["last_kst"][11:], "06:00")   # 11월(서머타임 끝) 16:00 ET = 06:00 KST
        self.assertEqual(next(r for r in sp["ranges"] if r["key"] == "1y")["base"], None)   # 1년치가 없으면 기준선 없음

    def test_credit_percentile_matches_retail_heat(self):
        d = date(2020, 1, 1)
        for i in range(1400):
            self.conn.execute("INSERT INTO retail_flows(date, credit_total) VALUES (?,?)",
                              ((d + timedelta(days=i)).isoformat(), 1e13 + (i % 97) * 1e10 + i * 1e8))
        tile = next(t for t in mo.overview(self.conn, "kr", KST_0930)["tiles"] if t["key"] == "credit")
        ref = [p for p in rh.with_percentiles(rh.series(self.conn)) if p.get("credit_total") is not None][-1]
        self.assertAlmostEqual(tile["growth_20"], ref["credit_growth"])
        self.assertEqual(tile["pctile"], ref["credit_growth_pct"])
        self.assertEqual(len(tile["series"]), 20)

    def test_tiles_keep_shape_without_data(self):
        o = mo.overview(self.conn, "us", KST_0930)
        self.assertEqual([t["key"] for t in o["tiles"]], ["fear_greed", "us10y", "dxy", "wti"])
        self.assertTrue(all(t["value"] is None and t["series"] == [] for t in o["tiles"]))

    def test_api_is_fast_and_matches_model(self):
        client = TestClient(app)
        with patch.object(spine_market_overview, "get_connection", return_value=self.conn):
            self.assertEqual(client.get("/api/spine/market/kr/overview").status_code, 200)
            t = time.perf_counter()
            r = client.get("/api/spine/market/kr/overview")
            took = time.perf_counter() - t
            self.assertEqual(client.get("/api/spine/market/jp/overview").status_code, 422)
        self.assertEqual(r.json()["market"], "kr")
        self.assertLess(took, 0.1)


if __name__ == "__main__":
    unittest.main()

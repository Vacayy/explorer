"""기술적 분석 스캔: 사건/상태/미평가 분류, 차트 오버레이, 미국 시세 표 (D-190)."""
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import technical_scan as ts
from routers import technical_scan as router_module


def rows(closes, start=date(2025, 1, 1), highs=None):
    out, day = [], start
    for i, close in enumerate(closes):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        high = highs[i] if highs else close + 1
        out.append({"date": day.isoformat(), "open": float(close), "high": float(high), "low": float(close) - 1, "close": float(close), "volume": 100.0 + i, "shares": 1000.0})
        day += timedelta(days=1)
    return out


class ScanTests(unittest.TestCase):
    def test_states_signals_and_unavailable_are_separated(self):
        # 300 bars of a steady uptrend → 정배열 상태 pass; 마지막 날 20일 신고가 + 거래량 증가 사건.
        series = [100 + i * 0.5 for i in range(300)] + [260]
        result = ts.scan_rows(rows(series), within=5)
        ids = lambda items: {e["id"] for e in items}
        self.assertIn("sma_bullish_order", ids(e for e in result["states"] if e["status"] == "pass"))
        self.assertIn("high_20d", ids(result["signals"]))
        self.assertEqual(result["signals"][0]["date"], result["as_of"], "newest signals come first")
        self.assertTrue(all(e["within_days"] == 5 for e in result["signals"]))
        self.assertTrue(all(e["within_days"] == 1 for e in result["states"]))
        self.assertEqual(result["counts"]["evaluated"], len(ts.scannable()))
        self.assertEqual(result["counts"]["passed"] + result["counts"]["failed"] + result["counts"]["unavailable"], result["counts"]["evaluated"])

    def test_short_history_is_unavailable_not_failed(self):
        result = ts.scan_rows(rows([10, 11, 12, 13, 14]), within=5)
        self.assertEqual(result["signals"], [])
        self.assertTrue(result["counts"]["unavailable"] >= result["counts"]["evaluated"] - 5, result["counts"])
        self.assertTrue(all(e["reason"] for e in result["unavailable"]))

    def test_chart_overlays_carry_structure_lines_and_dedupe_pivots(self):
        scan = {"signals": [{"id": "trendline_break_up", "label": "하락 추세선 상향 돌파", "category": "가격 구조", "date": "2026-09-04",
                             "evidence": {"pivots": [{"date": "2026-08-11", "price": 79800}, {"date": "2026-08-27", "price": 75500}],
                                          "line": [{"date": "2026-08-11", "price": 79800}, {"date": "2026-09-04", "price": 73155}]}},
                            {"id": "high_20d", "label": "20일 신고가 갱신", "category": "시세동향", "date": "2026-09-04", "evidence": None}],
                "states": [{"id": "lower_highs", "status": "pass", "evidence": {"pivots": [{"date": "2026-08-11", "price": 79800}]}}]}
        overlays = ts.chart_overlays(scan)
        self.assertEqual([m["label"] for m in overlays["markers"]], ["스윙", "스윙", "하락 추세선 상향 돌파", "20일 신고가 갱신"])
        self.assertEqual(len(overlays["lines"]), 1)

    def test_router_reads_kr_and_us_tables(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "db.sqlite"
        def connect():
            conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row
            return conn
        conn = connect()
        conn.executescript("""CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, market_cap REAL, shares REAL);
                              CREATE TABLE us_prices(stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);""")
        for r in rows([100 + i for i in range(80)]):
            conn.execute("INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?,?)", ("005930", r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"], 1e12, 100))
            conn.execute("INSERT INTO us_prices VALUES (?,?,?,?,?,?,?)", ("NVDA", r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
        conn.commit(); conn.close()
        with patch.object(router_module, "get_connection", connect):
            app = FastAPI(); app.include_router(router_module.router); client = TestClient(app)
            kr = client.get("/api/spine/technical-scan/005930", params={"within": 3}).json()
            us = client.get("/api/spine/technical-scan/nvda", params={"market": "us"}).json()
            self.assertEqual(client.get("/api/spine/technical-scan/000000").status_code, 404)
        self.assertEqual((kr["code"], kr["sessions"], kr["within"]), ("005930", 80, 3))
        self.assertEqual((us["code"], us["market"], us["sessions"]), ("NVDA", "us", 80))
        self.assertIn("high_20d", {e["id"] for e in kr["signals"]})


if __name__ == "__main__":
    unittest.main()

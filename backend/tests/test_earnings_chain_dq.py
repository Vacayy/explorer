"""분기 수익률(dq) — 발표 전 종가 → 다음 발표 전 거래일 종가, 업종 ETF 대비 %p. 다음 발표가 없으면 마지막 종가까지(partial)."""
import sqlite3
import unittest

from pipeline.earnings_chain import quarter_excess

DAYS = ["2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27",
        "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-11-03"]
# 기준 = 7/22(발표 7/23 전 종가). 다음 발표 10/22 → 끝 = 10/21
STOCK = [90, 100, 105, 106, 107, 118, 120, 130, 131, 140]
ETF = [99, 100, 101, 101, 102, 104, 105, 106, 106, 110]


class QuarterExcessTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE us_prices (stock_code TEXT, trade_date TEXT, close REAL, volume REAL)")
        for code, px in (("ROP", STOCK), ("SPY", ETF)):
            self.conn.executemany("INSERT INTO us_prices VALUES (?,?,?,?)", [(code, d, p, 1) for d, p in zip(DAYS, px)])

    def test_until_day_before_next_announcement(self):
        r = quarter_excess(self.conn, "ROP", "2026-07-23", "SPY", "2026-10-22", "2026-11-06")
        self.assertEqual(r, {"dq": 15.0, "dq_partial": False, "dq_end": "2026-10-21"})   # +20% - +5%

    def test_no_next_announcement_runs_to_latest_close(self):
        r = quarter_excess(self.conn, "ROP", "2026-10-22", "SPY", None, "2026-11-06")
        # 기준 10/21 (120, 105) → 11/03 (140, 110): +16.67% - +4.76%
        self.assertEqual(r, {"dq": 11.9, "dq_partial": True, "dq_end": "2026-11-03"})

    def test_no_price_after_announcement(self):
        r = quarter_excess(self.conn, "ROP", "2026-11-04", "SPY", None, "2026-11-06")
        self.assertEqual(r, {"dq": None, "dq_partial": None, "dq_end": None})


if __name__ == "__main__":
    unittest.main()

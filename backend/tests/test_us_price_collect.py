"""미국 시세 보유 현황·버튼 주도 수집 (docs/specs/us-dossier.md)."""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import us_data


class PriceStatus(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:"); self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE us_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, fetched_at TEXT,
                                    PRIMARY KEY (stock_code, trade_date));
            INSERT INTO us_prices VALUES ('NVDA','2026-09-18',1,1,1,1,1,'2026-09-19 07:00:00');
            INSERT INTO us_prices VALUES ('AAPL','2026-07-29',1,1,1,1,1,'2026-07-30 07:00:00');
        """)

    def test_states(self):
        self.assertEqual(us_data.price_status(self.conn, "intc")["state"], "missing")
        fresh = us_data.price_status(self.conn, "NVDA")
        self.assertEqual((fresh["state"], fresh["rows"], fresh["last_date"], fresh["fetched_at"]), ("fresh", 1, "2026-09-18", "2026-09-19T07:00:00Z"))
        stale = us_data.price_status(self.conn, "AAPL")
        self.assertEqual(stale["state"], "stale"); self.assertEqual(stale["stale_days"], 51)

    def test_collect_reports_failures_instead_of_silent_zero(self):
        class Empty:
            empty = True
        class FakeTicker:
            def __init__(self, t): pass
            def history(self, **kwargs): return Empty()
        with patch.dict("sys.modules", {"yfinance": type("yf", (), {"Ticker": FakeTicker})}):
            with self.assertRaises(us_data.PriceCollectError):
                us_data.collect_prices("ZZZZ")
        class Boom:
            def __init__(self, t): pass
            def history(self, **kwargs): raise ConnectionError("offline")
        with patch.dict("sys.modules", {"yfinance": type("yf", (), {"Ticker": Boom})}):
            with self.assertRaises(us_data.PriceCollectError) as ctx:
                us_data.collect_prices("INTC")
        self.assertIn("ConnectionError", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

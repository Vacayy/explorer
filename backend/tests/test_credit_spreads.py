"""회사채 스프레드 (D-230) — 보간·가격→수익률·부도확률·변화·수집. 수익률은 모두 가상 값."""
import sqlite3
import unittest
from datetime import date, timedelta
from unittest import mock

from pipeline import credit_spreads as cs


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cs.ensure_schema(c)
    return c


class FakeSource:
    def __init__(self, kind="yield"):
        self.kind = kind

    def resolve(self, company):
        if company["ticker"] != "ORCL":
            return None
        maturity = (date.today() + timedelta(days=int(365.25 * 6))).isoformat()
        return {"symbol": "X:ORCL", "description": "가상 5% 채권", "coupon": 5.0, "maturity": maturity, "rating_sp": "BBB-",
                "rating_moodys": None, "outstanding": 1e9, "source": "TRACE", "value_kind": self.kind}

    def history(self, symbol, bars):
        today = date.today()
        if self.kind == "price":
            return [((today - timedelta(days=d)).isoformat(), 100.0) for d in (40, 0)]
        return [((today - timedelta(days=d)).isoformat(), 7.0 if d else 6.0) for d in (40, 0)]


class CreditTests(unittest.TestCase):
    def test_interpolate_and_bounds(self):
        curve = [(1, 4.0), (5, 5.0), (10, 6.0)]
        self.assertAlmostEqual(cs.interpolate(curve, 3), 4.5)
        self.assertEqual(cs.interpolate(curve, 0.5), 4.0)
        self.assertEqual(cs.interpolate(curve, 30), 6.0)
        self.assertIsNone(cs.interpolate([], 3))

    def test_ytm_from_price_par_and_discount(self):
        settle, maturity = date(2026, 1, 1), date(2032, 1, 1)
        self.assertAlmostEqual(cs.ytm_from_price(100, 5.0, settle, maturity), 5.0, places=2)
        self.assertGreater(cs.ytm_from_price(90, 5.0, settle, maturity), 5.0)
        self.assertIsNone(cs.ytm_from_price(100, 5.0, maturity, settle))

    def test_default_probability_matches_reference_screen(self):
        self.assertEqual(cs.default_probability(1058), 58.6)
        self.assertEqual(cs.default_probability(239), 18.1)
        self.assertIsNone(cs.default_probability(None))
        self.assertEqual(cs.default_probability(-3), 0.0)

    def test_hy_flag(self):
        self.assertTrue(cs.is_hy("BB+", None))
        self.assertTrue(cs.is_hy(None, "Ba3"))
        self.assertFalse(cs.is_hy("BBB-", "Baa3"))

    def test_collect_then_table_spread_and_change(self):
        c = db()
        days = [(date.today() - timedelta(days=d)).isoformat() for d in (45, 40, 0)]
        c.executemany("INSERT INTO treasury_curve VALUES (?, ?, ?)", [(d, t, 4.0) for d in days for t in (1, 10)])
        with mock.patch.object(cs, "update_treasury", lambda conn, days: 0), mock.patch.object(cs.time, "sleep", lambda s: None):
            r = cs.collect(c, FakeSource())
        self.assertEqual((r["ok"], len(r["failed"])), (1, len(cs.COMPANIES) - 1))
        with mock.patch.object(cs, "source", lambda: object()):
            t = cs.table(c)
        row = next(x for x in t["rows"] if x["ticker"] == "ORCL")
        self.assertEqual((row["spread_bp"], row["chg_1m"], row["pd_pct"]), (200, -100, cs.default_probability(200)))
        self.assertTrue(t["configured"])
        h = cs.history(c, ["ORCL", "NOPE"])
        self.assertEqual(h["tickers"], ["ORCL"])
        self.assertEqual(h["points"][-1]["treasury"], 4.0)

    def test_price_quotes_become_yields(self):
        c = db()
        c.execute("INSERT INTO treasury_curve VALUES (?, 5, 4.0)", (date.today().isoformat(),))
        with mock.patch.object(cs, "update_treasury", lambda conn, days: 0), mock.patch.object(cs.time, "sleep", lambda s: None):
            cs.collect(c, FakeSource("price"), tickers=["ORCL"])
        ytm = c.execute("SELECT ytm FROM credit_quotes ORDER BY date DESC").fetchone()[0]
        self.assertAlmostEqual(ytm, 5.0, places=1)                 # 액면가 → 쿠폰 수준

    def test_missing_source_is_explicit(self):
        with mock.patch.object(cs, "source", lambda: None):
            with self.assertRaises(cs.NotConfigured):
                cs.collect(db())
            self.assertFalse(cs.table(db())["configured"])


if __name__ == "__main__":
    unittest.main()

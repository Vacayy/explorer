"""포트폴리오 원장 (D-212). 금액은 전부 가상값 — 공개 저장소에 실제 보유를 쓰지 않는다."""
import sqlite3
import unittest
from unittest import mock

from pipeline import portfolio as pf
from pipeline.watch_rules import SCHEMA as WATCH_SCHEMA


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(WATCH_SCHEMA + pf.SCHEMA + """
        CREATE TABLE companies (stock_code TEXT PRIMARY KEY, corp_name TEXT);
        CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, close REAL);
        INSERT INTO companies VALUES ('AAAAAA', '가나'), ('BBBBBB', '다라');
    """)
    return conn


def prices(conn, code, rows):
    conn.executemany("INSERT INTO stock_prices VALUES (?,?,?)", [(code, d, c) for d, c in rows])


def tx(conn, **kw):
    return pf.add_transaction(conn, {"note": "", "stock_code": None, "price": None, **kw})


class LedgerTests(unittest.TestCase):
    def test_moving_average_and_sell_keeps_avg(self):
        led = pf.replay([
            {"id": 1, "trade_date": "2026-01-01", "kind": "deposit", "amount": 1000, "stock_code": None, "price": None},
            {"id": 2, "trade_date": "2026-01-01", "kind": "buy", "amount": 100, "stock_code": "AAAAAA", "price": 10},
            {"id": 3, "trade_date": "2026-01-02", "kind": "buy", "amount": 200, "stock_code": "AAAAAA", "price": 20},
            {"id": 4, "trade_date": "2026-01-03", "kind": "sell", "amount": 150, "stock_code": "AAAAAA", "price": 30},
        ])
        pos = led.positions["AAAAAA"]
        self.assertAlmostEqual(pos.avg, 15.0)          # (100+200)/(10+10)
        self.assertAlmostEqual(pos.qty, 15.0)          # 20 - 150/30
        self.assertAlmostEqual(led.cash, 850.0)

    def test_realized_trades_use_average_at_sale_and_mark_full_exit(self):
        txs = [
            {"id": 1, "trade_date": "2026-01-01", "kind": "deposit", "amount": 1000, "stock_code": None, "price": None},
            {"id": 2, "trade_date": "2026-01-01", "kind": "buy", "amount": 200, "stock_code": "AAAAAA", "price": 10},   # 20주
            {"id": 3, "trade_date": "2026-01-05", "kind": "sell", "amount": 120, "stock_code": "AAAAAA", "price": 12},  # 10주 +20
            {"id": 4, "trade_date": "2026-01-08", "kind": "sell", "amount": 80, "stock_code": "AAAAAA", "price": 8},    # 10주 −20
        ]
        closed, gain = pf.realized_trades(txs)
        self.assertAlmostEqual(gain, 0.0)
        self.assertEqual([(c["return_pct"], c["full"], c["holding_days"]) for c in closed], [(20.0, False, 4), (-20.0, True, 7)])
        self.assertEqual({c["avg_price"] for c in closed}, {10.0})   # 매도는 평단 유지

    def test_twr_ignores_deposit(self):
        txs = [
            {"id": 1, "trade_date": "2026-01-01", "kind": "deposit", "amount": 100, "stock_code": None, "price": None},
            {"id": 2, "trade_date": "2026-01-01", "kind": "buy", "amount": 100, "stock_code": "AAAAAA", "price": 10},
            {"id": 3, "trade_date": "2026-01-03", "kind": "deposit", "amount": 1000, "stock_code": None, "price": None},
        ]
        pts = pf.valuation(txs, {"AAAAAA": [("2026-01-01", 10), ("2026-01-02", 11), ("2026-01-03", 11)]})
        self.assertEqual([p["date"] for p in pts], ["2026-01-01", "2026-01-02", "2026-01-03"])
        self.assertAlmostEqual(pts[1]["cum_return_pct"], 10.0)
        self.assertAlmostEqual(pts[2]["cum_return_pct"], 10.0)   # 입금은 수익이 아니다
        self.assertAlmostEqual(pts[2]["day_return_pct"], 0.0)

    def test_inception_before_first_close_uses_last_close(self):
        txs = [{"id": 1, "trade_date": "2026-01-05", "kind": "deposit", "amount": 100, "stock_code": None, "price": None},
               {"id": 2, "trade_date": "2026-01-05", "kind": "buy", "amount": 100, "stock_code": "AAAAAA", "price": 10}]
        pts = pf.valuation(txs, {"AAAAAA": [("2026-01-04", 9)]})
        self.assertEqual(pts[-1]["date"], "2026-01-05")
        self.assertAlmostEqual(pts[-1]["cum_return_pct"], -10.0)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        prices(self.conn, "AAAAAA", [("2026-01-01", 10), ("2026-01-02", 12)])

    def test_buy_funds_shortfall_and_syncs_members_without_amounts(self):
        tx(self.conn, trade_date="2026-01-01", kind="buy", stock_code="AAAAAA", amount=500, price=10)
        kinds = [r["kind"] for r in self.conn.execute("SELECT kind FROM portfolio_transactions ORDER BY id")]
        self.assertEqual(kinds, ["deposit", "buy"])
        m = self.conn.execute("SELECT * FROM stock_group_members").fetchone()
        self.assertEqual((m["stock_code"], m["bought_at"], m["quantity"], m["avg_price"]), ("AAAAAA", "2026-01-01", None, None))

    def test_rejects_oversell_and_breaking_delete(self):
        tx(self.conn, trade_date="2026-01-01", kind="buy", stock_code="AAAAAA", amount=500, price=10)
        with self.assertRaises(pf.LedgerError):
            tx(self.conn, trade_date="2026-01-02", kind="sell", stock_code="AAAAAA", amount=1000, price=10)
        deposit_id = self.conn.execute("SELECT id FROM portfolio_transactions WHERE kind='deposit'").fetchone()["id"]
        with self.assertRaises(pf.LedgerError):
            pf.delete_transaction(self.conn, deposit_id)
        with self.assertRaises(pf.LedgerError):
            pf.add_transaction(self.conn, {"trade_date": "2026-01-02", "kind": "buy", "stock_code": "AAAAAA",
                                           "amount": 1, "price": 10, "note": ""}, fund_shortfall=False)

    def test_sell_all_uses_holding_quantity_at_trade_date(self):
        tx(self.conn, trade_date="2026-01-01", kind="deposit", amount=1000)
        tx(self.conn, trade_date="2026-01-01", kind="buy", stock_code="AAAAAA", amount=500, price=10)   # 50주
        tx(self.conn, trade_date="2026-01-03", kind="sell", stock_code="AAAAAA", amount=None, price=12, sell_all=True)
        led = pf.replay(pf._txs(self.conn, pf.group_id(self.conn)))
        self.assertNotIn("AAAAAA", led.positions)
        self.assertAlmostEqual(led.cash, 500 + 600)
        with self.assertRaises(pf.LedgerError):
            tx(self.conn, trade_date="2026-01-04", kind="sell", stock_code="AAAAAA", amount=None, price=12, sell_all=True)

    def test_price_defaults_to_last_close(self):
        tx(self.conn, trade_date="2026-01-03", kind="buy", stock_code="AAAAAA", amount=120)
        self.assertEqual(self.conn.execute("SELECT price FROM portfolio_transactions WHERE kind='buy'").fetchone()["price"], 12)

    def test_read_outputs_carry_no_amounts_or_quantities(self):
        tx(self.conn, trade_date="2026-01-01", kind="deposit", amount=777)
        tx(self.conn, trade_date="2026-01-01", kind="buy", stock_code="AAAAAA", amount=500, price=10)
        tx(self.conn, trade_date="2026-01-02", kind="sell", stock_code="AAAAAA", amount=120, price=12)
        s = pf.summary(self.conn)
        self.assertAlmostEqual(s["total_return_pct"], (397 + 40 * 12) / 777 * 100 - 100, places=1)
        self.assertAlmostEqual(s["realized_pct"], 10 * 2 / 777 * 100, places=2)      # 원금 대비 비율만
        self.assertAlmostEqual(s["unrealized_pct"], 40 * 2 / 777 * 100, places=2)
        self.assertEqual(len(s["closed"]), 1)
        self.assertAlmostEqual(s["cash_weight_pct"], 397 / (397 + 40 * 12) * 100, places=1)
        blobs = [s, pf.history(self.conn), pf.transactions(self.conn)]
        text = repr(blobs)
        for banned in ("amount", "qty", "quantity", "value", "777", "500", "277"):
            self.assertNotIn(banned, text)


class LiveQuoteTests(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        prices(self.conn, "AAAAAA", [("2026-01-05", 10)])
        tx(self.conn, trade_date="2026-01-05", kind="buy", stock_code="AAAAAA", amount=100, price=10)
        self.calls = 0

    def fetch(self, codes):
        self.calls += 1
        return [{"stock_code": "AAAAAA", "price": 12, "change_pct": 20.0, "market_status": "OPEN", "traded_at": "2026-01-06T10:00:00+09:00"}]

    def test_market_hours(self):
        kst = pf.KST
        self.assertTrue(pf.market_hours(pf.datetime(2026, 1, 6, 9, 0, tzinfo=kst)))
        self.assertTrue(pf.market_hours(pf.datetime(2026, 1, 6, 15, 39, tzinfo=kst)))
        self.assertFalse(pf.market_hours(pf.datetime(2026, 1, 6, 15, 40, tzinfo=kst)))
        self.assertFalse(pf.market_hours(pf.datetime(2026, 1, 10, 11, 0, tzinfo=kst)))   # 토요일

    def test_live_quote_extends_today_and_respects_ttl(self):
        with mock.patch.object(pf, "market_hours", return_value=True):
            pf.refresh_quotes(self.conn, {"AAAAAA"}, fetch=self.fetch)
            pf.refresh_quotes(self.conn, {"AAAAAA"}, fetch=self.fetch)      # 30분 안 — 다시 부르지 않음
            self.assertEqual(self.calls, 1)
            with mock.patch("pipeline.quotes.fetch_quotes", self.fetch):
                s = pf.summary(self.conn)
        h = s["holdings"][0]
        self.assertEqual((h["price_source"], h["last_close"], h["return_pct"], h["day_change_pct"]), ("live", 12, 20.0, 20.0))
        self.assertEqual(s["as_of"], "2026-01-06")
        self.assertEqual(s["quoted_at"], "2026-01-06T10:00:00+09:00")

    def test_close_wins_once_collected(self):
        with mock.patch.object(pf, "market_hours", return_value=True):
            pf.refresh_quotes(self.conn, {"AAAAAA"}, fetch=self.fetch)
        prices(self.conn, "AAAAAA", [("2026-01-06", 11)])                  # 16:10 종가 수집
        with mock.patch.object(pf, "market_hours", return_value=False):
            h = pf.summary(self.conn)["holdings"][0]
        self.assertEqual((h["price_source"], h["last_close"]), ("close", 11))

    def test_refresh_now_ignores_hours_and_ttl(self):
        with mock.patch.object(pf, "market_hours", return_value=False), mock.patch("pipeline.quotes.fetch_quotes", self.fetch):
            self.assertEqual(pf.refresh_now(self.conn)["quoted_at"], "2026-01-06T10:00:00+09:00")
            pf.refresh_now(self.conn)
        self.assertEqual(self.calls, 2)

    def test_outside_hours_does_not_fetch(self):
        with mock.patch.object(pf, "market_hours", return_value=False):
            pf.refresh_quotes(self.conn, {"AAAAAA"}, fetch=self.fetch)
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()

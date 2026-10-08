"""포트폴리오 알림 (D-214). 금액은 가상값."""
import unittest
from datetime import datetime
from unittest import mock

from pipeline import portfolio as pf
from pipeline import portfolio_alerts as pa
from tests.test_portfolio import db, prices, tx

NOW = datetime(2026, 1, 6, 10, 0, tzinfo=pf.KST)


def quote(price, change):
    return lambda codes: [{"stock_code": "AAAAAA", "price": price, "change_pct": change, "market_status": "OPEN",
                           "traded_at": "2026-01-06T10:00:00+09:00"}]


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        self.conn.executescript(pa.SCHEMA)
        prices(self.conn, "AAAAAA", [("2026-01-05", 10)])
        tx(self.conn, trade_date="2026-01-05", kind="buy", stock_code="AAAAAA", amount=777, price=10)
        self.sent = []

    def run_intraday(self, price, change, **kw):
        with mock.patch.object(pf, "market_hours", return_value=True), \
             mock.patch("pipeline.quotes.fetch_quotes", quote(price, change)), \
             mock.patch.object(pa, "_dart_today", lambda code, ymd: []):
            return pa.run("intraday", conn=self.conn, send=lambda t: self.sent.append(t) or True, now=NOW, **kw)

    def test_bucket(self):
        self.assertEqual([pa._bucket(v, 5) for v in (4.9, 5.0, 10.2, -5.1, -10.0, None)], [0, 1, 2, -1, -2, 0])

    def test_move_alert_once_per_bucket(self):
        self.assertEqual(self.run_intraday(10.6, 6.0)["sent"], 1)          # 전일 +6% → 한 번
        self.conn.execute("UPDATE portfolio_quotes SET fetched_at=0")
        self.assertEqual(self.run_intraday(10.7, 7.0)["sent"], 0)          # 같은 구간 → 다시 안 보냄
        self.conn.execute("UPDATE portfolio_quotes SET fetched_at=0")
        self.assertEqual(self.run_intraday(11.2, 12.0)["sent"], 2)         # +10% 구간 진입 + 평단 대비 +12% 구간
        self.assertIn("전일 대비 +12.0%", self.sent[-1])

    def test_dry_run_does_not_record(self):
        self.run_intraday(10.6, 6.0, dry_run=True)
        self.assertFalse(self.conn.execute("SELECT count(*) FROM portfolio_alerts_sent").fetchone()[0])
        self.conn.execute("UPDATE portfolio_quotes SET fetched_at=0")
        self.assertEqual(self.run_intraday(10.6, 6.0)["sent"], 1)

    def test_send_failure_releases_keys(self):
        with mock.patch.object(pf, "market_hours", return_value=True), \
             mock.patch("pipeline.quotes.fetch_quotes", quote(10.6, 6.0)), mock.patch.object(pa, "_dart_today", lambda c, d: []):
            with self.assertRaises(RuntimeError):
                pa.run("intraday", conn=self.conn, send=lambda t: False, now=NOW)
        self.assertFalse(self.conn.execute("SELECT count(*) FROM portfolio_alerts_sent").fetchone()[0])

    def test_close_summary_and_disclosure_without_amounts(self):
        prices(self.conn, "AAAAAA", [("2026-01-06", 11)])
        fake_scan = lambda conn, code, market, within: {"as_of": "2026-01-06", "signals": [
            {"id": "high_52w", "category": "추세·모멘텀", "status": "pass", "date": "2026-01-06", "label": "52주 신고가"},
            {"id": "sma_cross_down_5d", "category": "지표신호", "status": "pass", "date": "2026-01-06", "label": "5일 이평 하향돌파"}]}
        with mock.patch.object(pf, "market_hours", return_value=False), \
             mock.patch.object(pa, "refresh_events", lambda conn, hs, today: {"confirmed": 0}), \
             mock.patch.object(pa, "upcoming_soon", lambda conn, hs, today: "📅 3일 이내 일정\n· 01-08 가 실적 발표(예상) (예상)"), \
             mock.patch("pipeline.portfolio_flow.flow", lambda conn, hs, d: []), \
             mock.patch("pipeline.portfolio_flow.ensure_digests", lambda hs, d, f: {}), \
             mock.patch("pipeline.portfolio_flow.summary_lines", lambda f, d: ["· 가: 언급 급증 6건(7일 평균 1.0)"]), \
             mock.patch("pipeline.technical_scan.scan_company", fake_scan), \
             mock.patch.object(pa, "_dart_today", lambda c, d: [{"rcept_no": "20260106000001", "report_nm": "단일판매공급계약"}]):
            r = pa.run("close", conn=self.conn, send=lambda t: self.sent.append(t) or True, now=NOW)
        self.assertEqual(r["sent"], 3)
        text = "\n".join(self.sent)
        self.assertIn("52주 신고가", text)
        self.assertNotIn("5일 이평", text)                                 # 주요 신호만
        self.assertIn("단일판매공급계약", text)
        self.assertIn("계좌 +10.0%", text)
        self.assertIn("3일 이내 일정", text)
        self.assertIn("자료 흐름", text)
        self.assertNotIn("errors", r)
        for banned in ("777", "77.7", "수량"):
            self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()

"""종목 추적 위젯 — 조건 판정, 추적 대상(홈 배치) 읽기, 알림 시점(가격 조건=장중, 이평선 조건=마감)."""
import json
import sqlite3
import unittest

from pipeline.stock_tracker import _items, ensure, evaluate, tracked_codes


def rows(closes):
    return [{"trade_date": f"2026-01-{i + 1:02d}" if i < 31 else f"2026-02-{i - 30:02d}", "open": c, "high": c, "low": c, "close": c, "volume": 100}
            for i, c in enumerate(closes)]


def cond(kind, **kw):
    return {"id": 1, "kind": kind, "role": kw.get("role", "exit"), "level": kw.get("level"), "ma": kw.get("ma"), "done": kw.get("done", 0), "label": "x"}


class EvaluateTests(unittest.TestCase):
    def test_price_conditions(self):
        r = rows([100] * 5)
        self.assertEqual(evaluate(cond("price_below", level=95), 94, r)["status"], "met")
        e = evaluate(cond("price_below", level=95), 100, r)
        self.assertEqual((e["status"], e["distance_pct"]), ("not_met", 5.3))
        self.assertEqual(evaluate(cond("price_above", level=110), 111, r)["status"], "met")

    def test_moving_average_conditions(self):
        r = rows([100] * 19 + [120])               # 20일선 = 101, 종가 120
        e = evaluate(cond("close_above_ma", ma=20), 120, r)
        self.assertEqual((e["status"], e["ref"]), ("met", 101))
        self.assertEqual(evaluate(cond("close_above_ma", ma=60), 120, r)["status"], "unknown")   # 이력 부족

    def test_manual_check(self):
        self.assertEqual(evaluate(cond("manual"), None, [])["status"], "pending")
        self.assertEqual(evaluate(cond("manual", done=1), None, [])["status"], "met")


class TrackedTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure(self.conn)
        self.conn.executescript("""CREATE TABLE home_boards (id INTEGER PRIMARY KEY, label TEXT, sort INTEGER, layout_json TEXT);
            CREATE TABLE companies (stock_code TEXT, corp_name TEXT, corp_code TEXT);
            CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);
            CREATE TABLE portfolio_quotes (stock_code TEXT, price REAL, change_pct REAL, market_status TEXT, traded_at TEXT, fetched_at REAL);""")
        items = [{"i": "track.stock#0", "widget": "track.stock", "params": {"code": "111111"}},
                 {"i": "market.us#0", "widget": "market.us", "params": None},
                 {"i": "track.stock#1", "widget": "track.stock", "params": {"code": "111111"}}]
        self.conn.execute("INSERT INTO home_boards VALUES (1, '대시보드', 0, ?)", (json.dumps(items),))
        self.conn.execute("INSERT INTO home_boards VALUES (2, '보유', 1, ?)", (json.dumps(items[:1]),))
        self.conn.execute("INSERT INTO companies VALUES ('111111', '테스트', 'C1')")
        for i, c in enumerate([100] * 59 + [90]):
            self.conn.execute("INSERT INTO stock_prices VALUES ('111111', ?, ?, ?, ?, ?, 100)", (f"2026-0{1 + i // 28}-{i % 28 + 1:02d}", c, c, c, c))
        self.conn.execute("INSERT INTO tracker_conditions (stock_code, role, kind, level, label) VALUES ('111111','exit','price_below',95,'손절')")
        self.conn.execute("INSERT INTO tracker_conditions (stock_code, role, kind, ma, label) VALUES ('111111','exit','close_below_ma',60,'60일선 이탈')")

    def test_tracked_codes_come_from_home_widgets(self):
        self.assertEqual(tracked_codes(self.conn), ["111111"])     # 같은 종목 위젯이 여러 메뉴에 → 한 번

    def test_ma_condition_alerts_at_close_only(self):
        close = _items(self.conn, "close", "2026-03-05", live=False)
        self.assertTrue(any("60일선 이탈" in t for _, t in close))
        self.assertFalse(any("손절" in t and "60일선" not in t for _, t in close))   # 가격 조건은 마감 점검에서 보내지 않는다

    def test_price_condition_needs_live_quote(self):
        self.assertEqual(_items(self.conn, "intraday", "2026-03-05", live=True), [])        # 실시간 시세가 없으면 장중 가격 조건 판정 안 함
        self.conn.execute("INSERT INTO portfolio_quotes VALUES ('111111', 94, -6.0, 'OPEN', '2026-03-06 10:00', 0)")
        keys = [k for k, _ in _items(self.conn, "intraday", "2026-03-06", live=True)]
        self.assertIn("track-cond:2026-03-06:1", keys)
        self.assertIn("track-day:2026-03-06:111111:-1", keys)



class HeadlineTests(unittest.TestCase):
    def test_disclosure_alert_post(self):
        from pipeline.stock_tracker import _headline
        t = "2026.10.20 11:24:29\n기업명: 뉴파워프라즈마 A144960\n보고서명: 주식등의대량보유상황보고서(약식)\n대표보고 : JP\n보고후 : 5.37%"
        self.assertEqual(_headline(t), "주식등의대량보유상황보고서(약식) · 보고 후 5.37%")

    def test_plain_post_skips_stamp(self):
        from pipeline.stock_tracker import _headline
        self.assertEqual(_headline("2026.10.20 11:24:29\n코리아써키트 SoCAMM 물량 확대"), "코리아써키트 SoCAMM 물량 확대")


if __name__ == "__main__":
    unittest.main()

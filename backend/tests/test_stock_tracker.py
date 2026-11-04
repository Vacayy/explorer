"""종목 추적 — 조건 판정, 추적 대상(관심 종목 추적 표시) 읽기, 알림 시점(가격 조건=장중, 이평선 조건=마감), 미국 티커 판정."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from pipeline.stock_tracker import _items, ensure, evaluate, newly_met, tracked_codes


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
        from pipeline.watch_rules import SCHEMA
        self.conn.executescript(SCHEMA + """CREATE TABLE home_boards (id INTEGER PRIMARY KEY, label TEXT, sort INTEGER, layout_json TEXT);
            CREATE TABLE companies (stock_code TEXT, corp_name TEXT, corp_code TEXT);
            CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);
            CREATE TABLE portfolio_quotes (stock_code TEXT, price REAL, change_pct REAL, market_status TEXT, traded_at TEXT, fetched_at REAL);""")
        gid = self.conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('관심 종목', 'watch')").lastrowid
        self.conn.execute("INSERT INTO stock_group_members (group_id, stock_code, tracked) VALUES (?, '111111', 1)", (gid,))
        self.conn.execute("INSERT INTO companies VALUES ('111111', '테스트', 'C1')")
        for i, c in enumerate([100] * 59 + [90]):
            self.conn.execute("INSERT INTO stock_prices VALUES ('111111', ?, ?, ?, ?, ?, 100)", (f"2026-0{1 + i // 28}-{i % 28 + 1:02d}", c, c, c, c))
        self.conn.execute("INSERT INTO tracker_conditions (stock_code, role, kind, level, label) VALUES ('111111','exit','price_below',95,'손절')")
        self.conn.execute("INSERT INTO tracker_conditions (stock_code, role, kind, ma, label) VALUES ('111111','exit','close_below_ma',60,'60일선 이탈')")

    def test_tracked_codes_come_from_member_flag(self):
        self.assertEqual(tracked_codes(self.conn), ["111111"])

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



class SourceTransitionTests(unittest.TestCase):
    """추적 원천 이행(ia-redesign §10.2) — 위젯(옛) + 관심 종목 추적 표시(새)의 합집합, 일회 복사, 두 원천 비교."""

    def setUp(self):
        from pipeline.watch_rules import SCHEMA
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA + """CREATE TABLE home_boards (id INTEGER PRIMARY KEY, label TEXT, sort INTEGER, layout_json TEXT);
            CREATE TABLE companies (stock_code TEXT, corp_name TEXT, corp_code TEXT);""")
        self.conn.executemany("INSERT INTO companies VALUES (?, ?, ?)", [(c, f"회사{c}", c) for c in ("111111", "222222", "333333", "444444")])
        self.gid = self.conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('관심 종목', 'watch')").lastrowid

    def widgets(self, *codes, board=1, sort=0):
        items = [{"i": f"track.stock#{i}", "widget": "track.stock", "params": {"code": c}} for i, c in enumerate(codes)]
        self.conn.execute("INSERT INTO home_boards VALUES (?, 'x', ?, ?)", (board, sort, json.dumps(items)))

    def member(self, code, tracked=0, group_id=None):
        self.conn.execute("INSERT INTO stock_group_members (group_id, stock_code, tracked) VALUES (?, ?, ?)", (group_id or self.gid, code, tracked))

    def test_tracked_codes_read_member_flag_only_and_ignore_widgets(self):
        from pipeline.stock_tracker import tracked_codes
        self.widgets("222222", "111111")                         # 옛 원천(위젯)은 더 읽지 않는다(개편 3d)
        self.member("333333", tracked=1)
        self.member("111111", tracked=1)
        self.member("444444", tracked=0)                         # 추적을 안 켠 관심 종목은 대상 아님
        self.assertEqual(tracked_codes(self.conn), ["333333", "111111"])
        self.conn.execute("UPDATE stock_group_members SET tracked=0 WHERE stock_code='111111'")
        self.assertEqual(tracked_codes(self.conn), ["333333"])   # 위젯이 남아 있어도 추적을 끄면 대상에서 빠진다

    def test_portfolio_group_tracked_flag_is_ignored(self):
        from pipeline.stock_tracker import member_codes
        pid = self.conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('보유', 'portfolio')").lastrowid
        self.member("111111", tracked=1, group_id=pid)
        self.assertEqual(member_codes(self.conn), [])

    def test_member_source_tolerates_missing_column(self):
        from pipeline.stock_tracker import member_codes, tracked_codes
        conn = sqlite3.connect(":memory:")
        conn.executescript("""CREATE TABLE stock_groups (id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
            CREATE TABLE stock_group_members (id INTEGER PRIMARY KEY, group_id INTEGER, stock_code TEXT);
            CREATE TABLE home_boards (id INTEGER PRIMARY KEY, label TEXT, sort INTEGER, layout_json TEXT);""")
        conn.execute("INSERT INTO home_boards VALUES (1, 'x', 0, ?)", (json.dumps([{"widget": "track.stock", "params": {"code": "111111"}}]),))
        self.assertEqual(member_codes(conn), [])
        self.assertEqual(tracked_codes(conn), [])                # 컬럼이 없으면(이관 전 DB) 대상 없음 — 오류로 멈추지 않는다

    def test_migration_adds_missing_marks_existing_and_is_idempotent(self):
        from pipeline.stock_tracker import migrate_widget_tracking, source_diff, tracked_codes, widget_codes
        self.widgets("111111", "222222", "333333")
        self.member("111111", tracked=0)
        self.member("222222", tracked=1)
        self.member("444444", tracked=1)                         # 새 원천에만 — 건드리지 않는다
        dry = migrate_widget_tracking(self.conn, dry_run=True)
        self.assertEqual([i["stock_code"] for i in dry["add"]], ["333333"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stock_group_members").fetchone()[0], 3)   # dry-run은 쓰지 않는다
        plan = migrate_widget_tracking(self.conn)
        self.assertEqual(([i["stock_code"] for i in plan["add"]], [i["stock_code"] for i in plan["mark"]], [i["stock_code"] for i in plan["same"]]),
                         (["333333"], ["111111"], ["222222"]))
        self.assertEqual(plan["add"][0]["name"], "회사333333")
        rows = dict(self.conn.execute("SELECT stock_code, tracked FROM stock_group_members WHERE group_id=?", (self.gid,)).fetchall())
        self.assertEqual(rows, {"111111": 1, "222222": 1, "333333": 1, "444444": 1})
        self.assertTrue(set(widget_codes(self.conn)) <= set(tracked_codes(self.conn)))   # 이관 뒤엔 위젯 종목이 모두 알림 대상
        again = migrate_widget_tracking(self.conn)
        self.assertEqual((again["add"], again["mark"], len(again["same"])), ([], [], 3))
        self.assertEqual(source_diff(self.conn)["widget_only"], [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM home_boards").fetchone()[0], 1)        # 옛 원천은 남긴다

    def test_migration_creates_default_group_when_missing(self):
        from pipeline.stock_tracker import migrate_widget_tracking
        self.conn.execute("DELETE FROM stock_groups")
        self.widgets("111111")
        plan = migrate_widget_tracking(self.conn)
        self.assertTrue(plan["create_group"])
        row = self.conn.execute("SELECT g.name, g.kind, m.tracked FROM stock_group_members m JOIN stock_groups g ON g.id=m.group_id").fetchone()
        self.assertEqual(tuple(row), ("관심 종목", "watch", 1))


class UsTrackingTests(unittest.TestCase):
    """미국 티커 추적 — us_prices 일봉으로 판정, 장 마감 점검에서만, 문구에 티커·미국·달러."""

    def setUp(self):
        from pipeline.watch_rules import SCHEMA
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure(self.conn)
        self.conn.executescript(SCHEMA + """CREATE TABLE companies (stock_code TEXT, corp_name TEXT, corp_code TEXT);
            CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);
            CREATE TABLE us_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, fetched_at TEXT);
            CREATE TABLE transcript_follow (ticker TEXT PRIMARY KEY, company_name TEXT, entity_id INTEGER);
            CREATE TABLE us_fundamentals (ticker TEXT PRIMARY KEY, data_json TEXT, fetched_at TEXT);
            CREATE TABLE portfolio_quotes (stock_code TEXT, price REAL, change_pct REAL, market_status TEXT, traded_at TEXT, fetched_at REAL);
            CREATE TABLE portfolio_alerts_sent (key TEXT PRIMARY KEY, sent_at TEXT DEFAULT (datetime('now')));""")
        gid = self.conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('관심 종목', 'watch')").lastrowid
        for code in ("111111", "ROP"):
            self.conn.execute("INSERT INTO stock_group_members (group_id, stock_code, tracked) VALUES (?, ?, 1)", (gid, code))
        self.conn.execute("INSERT INTO companies VALUES ('111111', '테스트', 'C1')")
        self.conn.execute("INSERT INTO transcript_follow VALUES ('ROP', 'Roper Technologies', NULL)")
        days = [f"2026-{1 + i // 28:02d}-{i % 28 + 1:02d}" for i in range(61)]
        for d, c in zip(days, [100] * 60 + [90]):        # 국내: 마지막 날 60일선 이탈
            self.conn.execute("INSERT INTO stock_prices VALUES ('111111', ?, ?, ?, ?, ?, 100)", (d, c, c, c, c))
        for d, c in zip(days, [480.0] * 60 + [450.5]):   # 미국: 마지막 미국 거래일 60일선 이탈 + 손절선 아래
            self.conn.execute("INSERT INTO us_prices VALUES ('ROP', ?, ?, ?, ?, ?, 1000, NULL)", (d, c, c, c, c))
        self.us_day = days[-1]
        self.conn.executemany("INSERT INTO tracker_conditions (stock_code, role, kind, level, ma, label) VALUES (?,?,?,?,?,?)", [
            ("111111", "exit", "close_below_ma", None, 60, "국내 60일선 이탈"),
            ("ROP", "exit", "close_below_ma", None, 60, "미국 60일선 이탈"),
            ("ROP", "exit", "price_below", 455, None, "미국 손절"),
            ("ROP", "entry", "price_above", 500, None, "미국 돌파")])

    def test_market_detection_and_tracked_mix(self):
        from pipeline.stock_tracker import market
        self.assertEqual(tracked_codes(self.conn), ["111111", "ROP"])
        self.assertEqual((market(self.conn, "111111"), market(self.conn, "ROP")), ("kr", "us"))

    def test_close_mode_evaluates_us_price_and_ma_on_last_us_bar(self):
        items = dict(_items(self.conn, "close", "2026-03-05", live=False))
        kr = [t for t in items.values() if "국내 60일선 이탈" in t]
        us = {k: t for k, t in items.items() if "ROP" in t}
        self.assertEqual(len(kr), 1)
        self.assertNotIn("미국", kr[0])
        self.assertEqual(len(us), 2)                                # 손절선·60일선 충족, 돌파는 미충족
        for k, t in us.items():
            self.assertTrue(k.startswith(f"track-cond:{self.us_day}:"))   # 키 = 미국 거래일 — 같은 봉으로 두 번 안 보낸다
            self.assertIn("Roper Technologies</b> (ROP·미국)", t)
            self.assertIn("현재 $450.50", t)
        self.assertTrue(any("(기준 $455.00)" in t for t in us.values()))
        self.assertTrue(any("60일선 $" in t for t in us.values()))

    def test_intraday_skips_us(self):
        self.conn.execute("INSERT INTO portfolio_quotes VALUES ('ROP', 400, -10.0, 'OPEN', '2026-03-06 10:00', 0)")   # 미국 종목엔 국내 실시간 시세를 쓰지 않는다
        self.assertFalse(any("ROP" in t for _, t in _items(self.conn, "intraday", "2026-03-06", live=True)))

    def test_alert_preview_mixed_kr_us(self):
        from pipeline import portfolio_alerts
        sent, refreshed, scanned = [], [], []

        def scan(conn, code, market, within):
            scanned.append((code, market))
            return {"as_of": None, "signals": []}
        real = portfolio_alerts.technical_signals
        with patch("pipeline.portfolio_alerts.new_disclosures", return_value=[]) as disc, \
             patch("pipeline.portfolio_alerts.technical_signals", side_effect=lambda conn, holdings: real(conn, holdings, scan=scan)):
            from pipeline.stock_tracker import alert
            n = alert(self.conn, "close", lambda text: sent.append(text) or True, "2026-03-05", dry_run=True, refresh_us=refreshed.extend)
        self.assertEqual(n, 3)
        self.assertEqual(refreshed, ["ROP"])                          # 미국 일봉만 캐시 갱신
        self.assertEqual(sorted(scanned), [("111111", "kr"), ("ROP", "us")])
        self.assertEqual([h["code"] for h in disc.call_args.args[0]], ["111111"])   # 공시(DART)는 국내만
        self.assertIn("ROP·미국", sent[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM portfolio_alerts_sent").fetchone()[0], 0)   # 미리보기는 기록하지 않는다

    def test_read_us_card(self):
        from pipeline import stock_tracker
        with patch.object(stock_tracker, "_technicals", return_value={}), patch.object(stock_tracker, "_issues", return_value={"disclosures": [], "docs_7d": 0, "docs": [], "target_prices": []}):
            card = stock_tracker.read(self.conn, "ROP")
        self.assertEqual((card["market"], card["name"], card["price"], card["source"], card["flows"]), ("us", "Roper Technologies", 450.5, "close", None))
        ma = next(c for c in card["conditions"] if c["kind"] == "close_below_ma")
        self.assertEqual((ma["status"], ma["ref"], ma["newly_met"]), ("met", 479.51, True))
        self.assertFalse(next(c for c in card["conditions"] if c["kind"] == "price_above")["newly_met"])


class NewlyMetTests(unittest.TestCase):
    def test_ma_condition_is_new_only_on_the_crossing_day(self):
        r = rows([100] * 60 + [90])
        c = cond("close_below_ma", ma=60)
        ev = evaluate(c, 90, r)
        self.assertTrue(newly_met(c, ev, {"source": "close"}, r))
        r2 = rows([100] * 60 + [90, 89])                  # 이틀째 이탈 — 새로 충족 아님
        self.assertFalse(newly_met(c, evaluate(c, 89, r2), {"source": "close"}, r2))

    def test_live_price_compares_against_last_close(self):
        r = rows([100] * 5)
        c = cond("price_below", level=95)
        self.assertTrue(newly_met(c, evaluate(c, 94, r), {"source": "live"}, r))

    def test_manual_check_is_new_on_the_kst_day_it_was_checked(self):
        c = cond("manual", done=1) | {"updated_at": "2026-11-04 16:00:00"}     # UTC 16시 = KST 11/05 01시
        ev = evaluate(c, None, [])
        self.assertTrue(newly_met(c, ev, {}, [], today="2026-11-05"))
        self.assertFalse(newly_met(c, ev, {}, [], today="2026-11-06"))


if __name__ == "__main__":
    unittest.main()

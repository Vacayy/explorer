"""운용 원칙 감시 — 규칙 검증·위반 판정·새로 어길 때만 알림 (D-227). 원칙·금액은 모두 가상."""
import sqlite3
import unittest

from pipeline import portfolio_principles as pp


def summary(weight=40.0, ret=-12.0, day=-1.0, cash=10.0, total=-5.0):
    return {"total_return_pct": total, "cash_weight_pct": cash, "holdings": [
        {"code": "AAAAAA", "name": "가나", "weight_pct": weight, "return_pct": ret, "day_change_pct": day, "entry_date": "2026-01-01"},
        {"code": "BBBBBB", "name": "다라", "weight_pct": 20.0, "return_pct": 3.0, "day_change_pct": 0.5, "entry_date": "2026-01-05"}]}


class PrincipleTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        pp.ensure_schema(self.conn)

    def test_validate_rejects_unknown_types_and_out_of_range(self):
        self.assertEqual(pp.validate([{"type": "max_weight", "params": {"pct": 30}}]), [{"type": "max_weight", "params": {"pct": 30.0}}])
        for bad in ([{"type": "buy_dip", "params": {"pct": 5}}], [{"type": "max_weight", "params": {"pct": 130}}],
                    [{"type": "stop_loss", "params": {"pct": True}}]):
            with self.assertRaises(ValueError):
                pp.validate(bad)

    def test_parse_keeps_valid_rules_and_returns_the_rest_as_unparsed(self):
        fake = lambda system, ctx, schema: {"rules": [{"type": "max_weight", "params": {"pct": 30}}, {"type": "stop_loss", "params": {"pct": 900}}],
                                            "unparsed": ["실적이 꺾이면 판다"]}
        result = pp.parse("한 종목 30% 이하, 실적이 꺾이면 판다", call=fake)
        self.assertEqual([r["summary"] for r in result["rules"]], ["보유 비중 상한 30%"])
        self.assertEqual(result["unparsed"][0], "실적이 꺾이면 판다")
        self.assertIn("평단 대비 손실 한도", result["unparsed"][1])

    def test_violations_cover_weight_loss_cash_and_account(self):
        pp.add(self.conn, "가상 원칙", [{"type": "max_weight", "params": {"pct": 30}}, {"type": "stop_loss", "params": {"pct": 10}},
                                       {"type": "min_cash", "params": {"pct": 20}}, {"type": "account_drawdown", "params": {"pct": 4}}])
        found = pp.violations(pp.principles(self.conn), summary(), today="2026-01-10")
        self.assertEqual(sorted(v["key"].split(":", 2)[2] for v in found), ["AAAAAA", "AAAAAA:2026-01-01", "account", "cash"])
        live = pp.violations(pp.principles(self.conn), summary(), today="2026-01-10", live_only=True)
        self.assertNotIn("account", [v["key"].split(":", 2)[2] for v in live])   # 계좌 누적 손실은 장 마감 점검만

    def test_alerts_once_until_cleared_then_again(self):
        pp.add(self.conn, "한 종목 30% 이하", [{"type": "max_weight", "params": {"pct": 30}}])
        sent = []
        send = lambda text: sent.append(text) or True
        self.assertEqual(pp.alert(self.conn, summary(weight=40), send), 1)
        self.assertEqual(pp.alert(self.conn, summary(weight=41), send), 0)        # 계속 어기는 중 — 다시 안 보냄
        self.assertEqual(pp.alert(self.conn, summary(weight=25), send), 0)        # 풀림 — 상태 삭제
        self.assertEqual(pp.alert(self.conn, summary(weight=35), send), 1)        # 다시 어김 — 다시 보냄
        self.assertIn("가나 비중 40.0%", sent[0])
        self.assertNotIn("원", sent[0].replace("원칙", ""))                       # 원화 금액 없음

    def test_notes_are_saved_replaced_and_rules_optional(self):
        pid = pp.add(self.conn, "가상 원문", [], ["물타기는 하지 않는다", "  "])
        self.assertEqual(pp.principles(self.conn)[0]["notes"], ["물타기는 하지 않는다"])
        with self.assertRaises(ValueError):
            pp.add(self.conn, "빈 해석", [], [])
        self.conn.execute("INSERT INTO portfolio_principle_state (key) VALUES (?)", (f"{pid}:0:cash",))
        self.assertTrue(pp.replace(self.conn, pid, "고친 원문", [{"type": "min_cash", "params": {"pct": 20}}], ["현금도 포지션이다"]))
        p = pp.principles(self.conn)[0]
        self.assertEqual((p["text"], p["notes"], len(p["rules"])), ("고친 원문", ["현금도 포지션이다"], 1))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM portfolio_principle_state").fetchone()[0], 0)   # 새 규칙 기준으로 다시 알림

    def test_entry_weight_rule_ignores_later_scaling_in(self):
        from pipeline import portfolio as pf
        txs = [{"id": 1, "trade_date": "2026-01-01", "kind": "deposit", "amount": 1000, "stock_code": None, "price": None},
               {"id": 2, "trade_date": "2026-01-02", "kind": "buy", "amount": 100, "stock_code": "AAAAAA", "price": 10},   # 진입 10%
               {"id": 3, "trade_date": "2026-01-05", "kind": "buy", "amount": 400, "stock_code": "AAAAAA", "price": 10},   # 불타기 — 무관
               {"id": 4, "trade_date": "2026-01-06", "kind": "buy", "amount": 400, "stock_code": "BBBBBB", "price": 10}]   # 진입 40%
        w = pf.entry_weights(txs, {"AAAAAA": [("2026-01-02", 10)], "BBBBBB": [("2026-01-06", 10)]})
        self.assertEqual(w, {"AAAAAA": 10.0, "BBBBBB": 40.0})
        pp.add(self.conn, "처음엔 25%까지만", [{"type": "max_entry_weight", "params": {"pct": 25}}])
        s = summary(weight=50)                                      # 보유 비중 50%라도 진입이 작았으면 위반 아님
        s["holdings"][0]["entry_weight_pct"], s["holdings"][1]["entry_weight_pct"] = 10.0, 40.0
        found = pp.violations(pp.principles(self.conn), s, today="2026-01-10")
        self.assertEqual([v["message"].split()[0] for v in found], ["다라"])

    def test_update_text_keeps_rules(self):
        pid = pp.add(self.conn, "줄1\n줄2", [{"type": "min_cash", "params": {"pct": 20}}])
        self.assertTrue(pp.update_text(self.conn, pid, "줄1\n줄2\n줄3 " + "가" * 5000))
        p = pp.principles(self.conn)[0]
        self.assertEqual((p["text"].count("\n"), len(p["rules"])), (2, 1))
        self.assertFalse(pp.update_text(self.conn, 999, "없음"))

    def test_failed_send_does_not_record_state(self):
        pp.add(self.conn, "현금 20% 이상", [{"type": "min_cash", "params": {"pct": 20}}])
        with self.assertRaises(RuntimeError):
            pp.alert(self.conn, summary(cash=10), lambda text: False)
        self.assertEqual(pp.alert(self.conn, summary(cash=10), lambda text: True), 1)


if __name__ == "__main__":
    unittest.main()


class ChatToolTests(unittest.TestCase):
    def test_chat_tool_carries_principle_text_and_ratios_but_no_amounts(self):
        from unittest import mock
        from pipeline import portfolio as pf
        from pipeline.chat_tools import get_portfolio
        from tests.test_portfolio import db, prices, tx
        raw = db()
        pp.ensure_schema(raw)

        class Keep:                                                 # 도구가 닫아도 메모리 DB 유지
            def __getattr__(self, name):
                return getattr(raw, name)

            def close(self):
                pass
        conn = Keep()
        prices(conn, "AAAAAA", [("2026-01-01", 10), ("2026-01-02", 12)])
        with mock.patch.object(pf, "connect", lambda: conn), mock.patch.object(pf, "refresh_quotes", lambda *a, **k: None):
            tx(conn, trade_date="2026-01-01", kind="deposit", amount=777)
            tx(conn, trade_date="2026-01-01", kind="buy", stock_code="AAAAAA", amount=500, price=10)
            pp.add(conn, "가상 원칙: 한 종목 30% 이하. 물타기는 하지 않는다.", [{"type": "max_weight", "params": {"pct": 30}}])
            r = get_portfolio()
        text = "\n".join(i["text"] for i in r.items)
        self.assertIn("물타기는 하지 않는다", text)                 # 기계가 못 푸는 문장도 대화 맥락으로 전달
        self.assertIn("지금 어긴 규칙: 가나 비중", text)
        for banned in ("777", "500", "277", "amount", "수량"):
            self.assertNotIn(banned, text)

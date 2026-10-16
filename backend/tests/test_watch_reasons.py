"""관심 종목 이유 감시 (portfolio-intelligence §6, D-227) — 보유 논지와 분리, 양방향 알림."""
import unittest
from unittest import mock

from pipeline import watch_reasons as wrs
from tests.test_portfolio_thesis import db


class WatchReasonTests(unittest.TestCase):
    def test_question_text_and_creator(self):
        self.assertEqual(wrs.question_text("가", " 증설 수혜 ", ""), "가 관심 이유: 증설 수혜")
        with mock.patch("pipeline.questions.decompose_question", return_value={"id": 3}) as dq:
            wrs.start("000001", "가", "증설 수혜", "수주 공시가 나오면")
        args, kw = dq.call_args
        self.assertEqual((kw["created_by"], kw["stock_code"]), ("watch", "000001"))
        self.assertIn("이렇게 되면 움직인다: 수주 공시가 나오면", args[0])
        self.assertIn("관심 종목", kw["hint"])

    def test_reasons_do_not_mix_with_holding_theses(self):
        c = db()                                                   # 000001에 보유 논지(created_by=portfolio) 1건
        self.assertEqual(wrs.reasons(c, ["000001"]), {})
        c.execute("INSERT INTO questions (id, text, status, lead_verdict, confirm_verdict, divergence, created_by, stock_code) "
                  "VALUES (2, '가 관심 이유', 'tracking', 'unknown', 'unknown', 'none', 'watch', '000001')")
        self.assertEqual(wrs.reasons(c, ["000001"])["000001"]["id"], 2)

    def test_alerts_when_leaning_either_way_once_per_state(self):
        c, sent = db(), []
        send = lambda t: sent.append(t) or True                   # noqa: E731
        c.execute("INSERT INTO questions (id, text, status, lead_verdict, confirm_verdict, divergence, created_by, stock_code) "
                  "VALUES (2, '가 관심 이유', 'tracking', 'unknown', 'unknown', 'none', 'watch', '000001')")
        members = [{"code": "000001", "name": "가"}]
        self.assertEqual(wrs.alert(c, members, send), 0)          # 아직 기울지 않음
        c.execute("UPDATE questions SET lead_verdict='leaning_yes' WHERE id=2")
        self.assertEqual(wrs.alert(c, members, send), 1)
        self.assertIn("선행 신호 지지", sent[0])
        self.assertIn("🟢", sent[0])
        self.assertEqual(wrs.alert(c, members, send), 0)          # 같은 상태는 한 번
        c.execute("UPDATE questions SET lead_verdict='leaning_no' WHERE id=2")
        self.assertEqual(wrs.alert(c, members, send), 1)          # 반대로 기울면 다시
        self.assertIn("선행 신호 약화", sent[1])


if __name__ == "__main__":
    unittest.main()

"""포트폴리오 논지 감시 (portfolio-intelligence §2)."""
import sqlite3
import unittest
from unittest import mock

from pipeline import portfolio_alerts as pa
from pipeline import portfolio_thesis as pt


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE questions (id INTEGER PRIMARY KEY, text TEXT, status TEXT, lead_verdict TEXT, confirm_verdict TEXT,
        divergence TEXT, verdict_summary TEXT, created_by TEXT DEFAULT 'portfolio', updated_at TEXT DEFAULT '2026-08-18 23:00:00');
        CREATE TABLE sub_questions (id INTEGER PRIMARY KEY, question_id INT, text TEXT, falsifier TEXT, verdict TEXT);""" + pa.SCHEMA)
    pt.ensure_schema(c)
    pt.ensure_schema(c)                                         # 두 번 불러도 안전
    c.execute("INSERT INTO questions (id, text, status, lead_verdict, confirm_verdict, divergence, verdict_summary, stock_code) "
              "VALUES (1,'가 논지','tracking','leaning_yes','mixed','none',NULL,'000001')")
    c.execute("INSERT INTO sub_questions VALUES (1,1,'HBM 수요 유지?','HBM 가격 하락 전환','leaning_yes')")
    return c


class ThesisTests(unittest.TestCase):
    def test_theses_carry_when_they_were_last_judged(self):
        # 판정 엔진(refresh_questions)이 꺼져도 화면이 옛 판정을 오늘 것처럼 쓰지 않게(08-19~ off였다)
        self.assertEqual(pt.theses(db(), ["000001"])["000001"]["judged_at"], "2026-08-18 23:00:00")

    def test_question_text_and_hint(self):
        self.assertEqual(pt.question_text("가", " 수주 증가 ", ""), "가 보유 논지: 수주 증가")
        self.assertIn("이렇게 되면 틀린 것: 투자 지연", pt.question_text("가", "수주", "투자 지연"))
        self.assertIn("000001", pt.KR_HINT.format(name="가", code="000001"))

    def test_start_passes_stock_and_hint_not_in_text(self):
        with mock.patch("pipeline.questions.decompose_question", return_value={"id": 9}) as dq:
            pt.start("000001", "가", "수주 증가", "투자 지연")
        args, kw = dq.call_args
        self.assertEqual(kw["stock_code"], "000001")
        self.assertNotIn("분해 안내", args[0])
        self.assertIn("분해 안내", kw["hint"])

    def test_alert_only_when_worse_and_once(self):
        c, sent = db(), []
        send = lambda t: sent.append(t) or True                  # noqa: E731
        hs = [{"code": "000001", "name": "가"}]
        self.assertEqual(pt.alert(c, hs, send), 0)               # 나쁜 신호 없음
        c.execute("UPDATE sub_questions SET verdict='leaning_no'")
        self.assertEqual(pt.alert(c, hs, send), 1)
        self.assertIn("반증 조건: HBM 가격 하락 전환", sent[0])
        self.assertEqual(pt.alert(c, hs, send), 0)               # 같은 상태는 한 번
        c.execute("UPDATE questions SET confirm_verdict='leaning_no'")
        self.assertEqual(pt.alert(c, hs, send), 1)               # 더 나빠지면 다시


if __name__ == "__main__":
    unittest.main()

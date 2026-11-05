"""질문 트리 — 프록시 줄의 관측은 최근 6건, obs_count는 전체 수 (ia-redesign §4.27 '프록시 줄에 관측 건수')."""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import questions
from tests.test_job_status import KeepOpen


class QuestionTreeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE questions(id INTEGER PRIMARY KEY, text TEXT, source_doc_id INTEGER);
            CREATE TABLE sub_questions(id INTEGER PRIMARY KEY, question_id INTEGER, text TEXT);
            CREATE TABLE proxy_registry(id INTEGER PRIMARY KEY, sub_question_id INTEGER, label TEXT);
            CREATE TABLE proxy_observations(id INTEGER PRIMARY KEY, proxy_id INTEGER, observed_at TEXT, value_num REAL, value_text TEXT, direction TEXT);
            CREATE TABLE scenarios(question_id INTEGER, event TEXT, answer TEXT, beneficiaries TEXT, created_at TEXT);
            INSERT INTO questions VALUES (1, 'AI 매출 전환?', NULL);
            INSERT INTO sub_questions VALUES (10, 1, '사용량');
            INSERT INTO proxy_registry VALUES (100, 10, '토큰'), (101, 10, '대기');
        """)
        self.conn.executemany("INSERT INTO proxy_observations(proxy_id, observed_at, value_text) VALUES (100, ?, 'x')",
                              [(f"2026-0{m}-01",) for m in range(1, 10)])

    def test_tree_keeps_six_latest_and_reports_total_count(self):
        with patch.object(questions, "get_connection", return_value=KeepOpen(self.conn)):
            t = questions.get_tree(1)
        p, waiting = t["sub_questions"][0]["proxies"]
        self.assertEqual((len(p["observations"]), p["obs_count"]), (6, 9))
        self.assertEqual(p["observations"][0]["observed_at"], "2026-09-01")
        self.assertEqual((waiting["observations"], waiting["obs_count"]), ([], 0))


if __name__ == "__main__":
    unittest.main()

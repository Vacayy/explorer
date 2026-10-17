"""서사 변화 요약(change_summary): 본 생성 호출이 같이 내는 1~2문장 + 옛 버전용 결정적 fallback.

홈 위젯 '이번 주 바뀐 서사'는 고리 목록 대신 이 한두 문장만 보여 준다 (docs/specs/world-model.md).
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from pipeline.narrative import (CHANGE_SUMMARY_MAX, _build_prompt, _persist_narrative,
                                change_summary_fallback, normalize_change_summary)


class NormalizeTests(unittest.TestCase):
    def test_strips_quotes_tags_and_whitespace(self):
        self.assertEqual(normalize_change_summary('  "[현재] 공급 부족 이야기에서\n  장기 계약 이야기로 옮겨 갔다" '),
                         "공급 부족 이야기에서 장기 계약 이야기로 옮겨 갔다")

    def test_non_string_or_blank_is_none(self):
        for v in (None, 3, ["a"], {"x": 1}, "   ", '""'):
            self.assertIsNone(normalize_change_summary(v), v)

    def test_long_text_is_clipped_at_a_boundary_with_ellipsis(self):
        s = normalize_change_summary("가" * 60 + ", " + "나" * 80)
        self.assertLessEqual(len(s), CHANGE_SUMMARY_MAX)
        self.assertEqual(s, "가" * 60 + "…")


class FallbackTests(unittest.TestCase):
    def test_takes_first_sentence(self):
        self.assertEqual(change_summary_fallback("핵심 축이 금리로 이동했다. 반면 유가 고리는 빠졌다."), "핵심 축이 금리로 이동했다.")

    def test_cuts_before_colon_explanation(self):
        self.assertEqual(change_summary_fallback("인과 구조가 재편됐다: 기존 'A → B' 경로가 빠지고 C가 들어왔다."),
                         "인과 구조가 재편됐다")

    def test_long_single_sentence_is_clipped_at_comma(self):
        drift = "유가→금리 고리가 빠지고 " + "자본 흐름 " * 12 + "이 새로 들어왔으며, " + "축이 이동했다 " * 10
        s = change_summary_fallback(drift)
        self.assertLessEqual(len(s), CHANGE_SUMMARY_MAX)
        self.assertTrue(s.endswith("들어왔으며…"), s)

    def test_empty_is_none(self):
        for v in (None, "", "  \n "):
            self.assertIsNone(change_summary_fallback(v))


class PersistTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "test.sqlite"
        with patch.object(database, "DB_PATH", path):
            database.init_db()
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)

    def persist(self, change):
        data = {"title": "제목", "narrative": "## 3줄 요약\n- 공급 부족\n", "change_summary": change}
        nid, version, _ = _persist_narrative(self.c, "메모리", data, [], "h")
        return version, self.c.execute("SELECT change_summary FROM narratives WHERE id=?", (nid,)).fetchone()[0]

    def test_first_version_drops_change_summary_and_later_version_stores_normalized(self):
        self.assertEqual(self.persist("첫 버전엔 비교 대상이 없다"), (1, None))
        self.assertEqual(self.persist("  공급 부족에서 장기 계약으로 무게가 옮겨 갔다 "), (2, "공급 부족에서 장기 계약으로 무게가 옮겨 갔다"))
        self.assertEqual(self.persist(None), (3, None))   # 모델이 키를 빠뜨려도 생성은 그대로

    def test_prompt_asks_for_change_summary_only_when_prior_version_exists(self):
        self.assertNotIn("change_summary", _build_prompt("메모리", [], [], []))
        self.persist(None)
        prev = self.c.execute("SELECT * FROM narratives WHERE topic='메모리'").fetchone()
        p = _build_prompt("메모리", [], [], [], prev)
        self.assertIn("change_summary", p)
        self.assertIn("직전 3줄 요약: 공급 부족", p)


if __name__ == "__main__":
    unittest.main()

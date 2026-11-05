"""통합 리포트 레이팅 어휘 — 매매 권유 표현을 비대칭 판단으로 낮춘다 (ia-redesign §4.27, 11-04). LLM은 부르지 않는다(가로챔)."""
import unittest
from unittest.mock import patch

from pipeline import report


class RatingWordingTests(unittest.TestCase):
    def test_lead_prompt_uses_asymmetry_words_not_trade_calls(self):
        seen = {}

        def fake(prompt, **kw):
            seen["prompt"] = prompt
            return "{}"
        with patch.object(report, "_call_claude_code", side_effect=fake):
            report._lead("반도체", "산업", "종목", {"fundamental": "", "technical": "", "sentiment": ""}, "bull", "bear")
        p = seen["prompt"]
        for word in ("Strong Buy", "Buy|", "Sell", "수혜받는"):
            self.assertNotIn(word, p)
        self.assertIn("상방 우위(비대칭 큼)|상방 우위|중립|하방 우위", p)
        self.assertNotIn("Hold", p)
        self.assertIn("비대칭이 크다", p)

    def test_old_english_ratings_map_to_new_words_and_order(self):
        self.assertEqual([report.RATING_ALIASES[k] for k in ("Strong Buy", "Buy", "Hold", "Sell")],
                         ["상방 우위(비대칭 큼)", "상방 우위", "중립", "하방 우위"])
        self.assertGreater(report.RATING_ORDER["상방 우위(비대칭 큼)"], report.RATING_ORDER["상방 우위"])
        self.assertGreater(report.RATING_ORDER["중립"], report.RATING_ORDER["하방 우위"])


if __name__ == "__main__":
    unittest.main()

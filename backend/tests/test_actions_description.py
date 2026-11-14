"""기업활동 목록 한 줄 설명 — 저장된 증자 상세·요약에서 결정적으로 만든다(LLM 0, D-306 5)."""
import unittest

from pipeline.actions import DESCRIPTION_MAX, action_description


def detail(**kw):
    base = {"method": None, "price_1st": None, "price_2nd": None, "price_final": None, "old_shares": None, "new_shares": None}
    return {**base, **kw}


class ActionDescriptionTests(unittest.TestCase):
    def test_raise_detail_wins(self):
        d = detail(method="제3자배정", price_1st=200_000, price_final=204_500, old_shares=152_126_544, new_shares=6_558_435)
        self.assertEqual(action_description("주요사항보고서(유상증자결정)", "긴 요약입니다.", d),
                         "제3자배정 · 확정 발행가 204,500원 · 신주 6,558,435주(기존 대비 4.3%)")

    def test_raise_detail_needs_two_parts(self):
        # 방식만 있으면 정보가 부족 — 요약 첫 문장으로 넘어간다
        self.assertEqual(action_description("유상증자결정", "A가 증자한다. 둘째 문장.", detail(method="주주배정")), "A가 증자한다.")

    def test_first_sentence_keeps_decimals(self):
        s = "합병비율은 1.0 : 0.0으로 신주 발행은 없다. 합병기일은 12월 4일이다."
        self.assertEqual(action_description("합병", s), "합병비율은 1.0 : 0.0으로 신주 발행은 없다.")

    def test_long_sentence_clipped(self):
        s = "가" * 40 + " " + "나" * 40 + " " + "다" * 60 + "이다."
        out = action_description("합병", s)
        self.assertLessEqual(len(out), DESCRIPTION_MAX)
        self.assertTrue(out.endswith("…"))

    def test_whitespace_collapsed(self):
        self.assertEqual(action_description("x", "  정정 핵심:\n\n 납입일 확정.  "), "정정 핵심: 납입일 확정.")

    def test_failed_summary_and_subsidiary_marker(self):
        self.assertEqual(action_description("회사분할결정(종속회사의주요경영사항)", "(원문 조회 실패)"), "자회사 관련 공시입니다.")
        self.assertIsNone(action_description("합병등종료보고서(합병)", "(원문 조회 실패)"))
        self.assertIsNone(action_description(None, None))


if __name__ == "__main__":
    unittest.main()

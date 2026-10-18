"""미국 분기 실적 — 3개월 값 우선, 누적값 차감, 달력 분기 키."""
import unittest

from pipeline.us_fundamentals import _merge_tags, _quarter_key, quarterly


def e(start, end, val, form="10-Q", filed="2026-01-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


class QuarterlyTests(unittest.TestCase):
    def test_quarter_keys(self):
        self.assertEqual(_quarter_key("2025-12-27"), "2025-12")   # 애플 회계 분기 끝
        self.assertEqual(_quarter_key("2026-03-31"), "2026-03")
        self.assertEqual(_quarter_key("2025-11-30"), "2025-12")   # 오라클(11월 말) → 4분기
        self.assertEqual(_quarter_key("2026-01-04"), "2025-12")   # 초순 마감은 직전 달

    def test_ytd_cash_flow_is_differenced(self):
        facts = [e("2025-09-28", "2025-12-27", 2.4), e("2025-09-28", "2026-03-28", 4.3),
                 e("2025-09-28", "2026-06-27", 6.8), e("2025-09-28", "2026-09-26", 10.0, "10-K")]
        q = quarterly(facts)
        self.assertEqual({k: round(v, 2) for k, v in q.items()}, {"2025-12": 2.4, "2026-03": 1.9, "2026-06": 2.5, "2026-09": 3.2})

    def test_discrete_quarter_wins_and_latest_filing_kept(self):
        facts = [e("2026-01-01", "2026-03-31", 30.0, filed="2026-04-30"), e("2026-01-01", "2026-03-31", 30.9, filed="2026-07-30"),
                 e("2025-07-01", "2026-03-31", 80.1)]
        self.assertEqual(quarterly(facts)["2026-03"], 30.9)


    def test_restated_annual_is_not_mixed_with_original_nine_months(self):
        # 엔벤트: 2022 연간이 2025년 10-K에서 사업 매각 반영으로 2,909 → 2,295로 수정. 수정된 9개월은 공시된 적 없다
        facts = [e("2022-01-01", "2022-09-30", 2167, filed="2022-10-28"), e("2022-01-01", "2022-09-30", 2167, filed="2023-10-27"),
                 e("2022-01-01", "2022-12-31", 2909, "10-K", filed="2023-02-28"), e("2022-01-01", "2022-12-31", 2909, "10-K", filed="2024-02-20"),
                 e("2022-01-01", "2022-12-31", 2295, "10-K", filed="2025-02-18")]
        self.assertEqual(quarterly(facts)["2022-12"], 742)


class FundingTests(unittest.TestCase):
    """회사채 발행 — 계정 전환(오라클)·발행 없는 분기 미보고(메타·MSFT) 회귀 (2026-10-18 점검)"""

    def test_tag_switch_mid_year_is_merged(self):
        # 오라클 FY26: 1분기는 LongTermDebt(0), 6·9개월·연간은 SeniorLongTermDebt
        gaap = {"ProceedsFromIssuanceOfLongTermDebt": {"units": {"USD": [e("2025-06-01", "2025-08-31", 0.0, filed="2025-09-10")]}},
                "ProceedsFromIssuanceOfSeniorLongTermDebt": {"units": {"USD": [
                    e("2025-06-01", "2025-11-30", 17.9, filed="2025-12-10"), e("2025-06-01", "2026-02-28", 44.5, filed="2026-03-10"),
                    e("2025-06-01", "2026-05-31", 46.1, "10-K", filed="2026-06-20")]}}}
        tags, units = _merge_tags(gaap, "debt_issue")
        q = {k: round(v, 1) for k, v in quarterly(units, zero_omit=True).items()}
        self.assertEqual(q, {"2025-09": 0.0, "2025-12": 17.9, "2026-03": 26.6, "2026-06": 1.6})
        self.assertEqual(len(tags), 2)

    def test_missing_first_quarter_means_zero(self):
        # 메타 2026: 1분기 10-Q에 항목 없음 → 6개월 누적 24.9는 전부 2분기
        q = quarterly([e("2026-01-01", "2026-06-30", 24.9)], zero_omit=True)
        self.assertEqual(q, {"2026-03": 0.0, "2026-06": 24.9})

    def test_revenue_does_not_assume_zero(self):
        self.assertEqual(quarterly([e("2026-01-01", "2026-06-30", 24.9)]), {})


if __name__ == "__main__":
    unittest.main()

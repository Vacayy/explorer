"""미국 분기 실적 — 3개월 값 우선, 누적값 차감, 달력 분기 키."""
import unittest

from pipeline.us_fundamentals import _quarter_key, quarterly


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


if __name__ == "__main__":
    unittest.main()

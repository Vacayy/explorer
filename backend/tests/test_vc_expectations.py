"""시장 기대치 — 칸 합계 성장률은 매출 가중(통화 맞춤), EPS 개정은 중앙값, 메모리는 전업 회사로."""
import unittest

from pipeline.vc_expectations import EXP_MEMBERS, _revision, aggregate


def m(cur, g, ccy="USD", eps=None, eps30=None):
    return {"currency": ccy, "periods": {"0q": {"rev_avg": cur, "rev_growth": g}, "0y": {"rev_avg": cur, "rev_growth": g, "eps_avg": eps, "eps_30d": eps30}}}


class ExpectationTests(unittest.TestCase):
    def test_aggregate_is_revenue_weighted_growth(self):
        # 150(+50%, 전년 100) + 110(+10%, 전년 100) → 260/200 − 1 = +30%
        self.assertEqual(aggregate([m(150, 0.5), m(110, 0.1)], "0q"), 30.0)

    def test_currency_is_normalized_before_weighting(self):
        # 대만달러 3200(=USD 100, +100%) + USD 100(0%) → 200/150 − 1 = +33.3%
        self.assertEqual(aggregate([m(3200, 1.0, "TWD"), m(100, 0.0)], "0q"), 33.3)

    def test_missing_growth_is_skipped(self):
        self.assertEqual(aggregate([m(150, 0.5), m(110, None)], "0q"), 50.0)
        self.assertIsNone(aggregate([], "0q"))

    def test_eps_revision_median_handles_negative_base(self):
        # +10%, −5%, 적자 축소(−2 → −1)는 개선(+50%)으로 — 중앙값 +10%
        self.assertEqual(_revision([m(1, 0, eps=1.1, eps30=1.0), m(1, 0, eps=0.95, eps30=1.0), m(1, 0, eps=-1.0, eps30=-2.0)], "eps_30d"), 10.0)

    def test_memory_uses_pure_play_consensus(self):
        """관측(한국 메모리 수출)과 같은 사업 — 삼성전자 회사 전체 컨센서스를 쓰면 기대가 희석된다"""
        self.assertNotIn("005930.KS", [s for s, _ in EXP_MEMBERS["memory"]])


if __name__ == "__main__":
    unittest.main()

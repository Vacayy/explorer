"""가파른 추세 판정 — 고르게 오른 상승만 통과하고, 한 번 튄 급등·횡보는 걸러진다."""
import unittest

from pipeline.trend_leaders import evaluate


def bars(closes):
    return [{"high": c * 1.01, "low": c * 0.99, "close": c} for c in closes]


class TrendLeaderTests(unittest.TestCase):
    def test_steady_steep_rise_passes(self):
        closes = [100.0] * 80 + [100 * 1.006 ** i for i in range(1, 81)]   # 80일 +61%, 고르게
        hit = evaluate(bars(closes), len(closes) - 1)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit["ret_60"], 30)
        self.assertGreater(hit["r2"], 0.95)

    def test_one_day_spike_fails(self):
        closes = [100.0] * 150 + [150.0] * 10                               # 하루 +50% 후 횡보
        self.assertIsNone(evaluate(bars(closes), len(closes) - 1))

    def test_sideways_fails(self):
        closes = [100 + (i % 5) for i in range(160)]
        self.assertIsNone(evaluate(bars(closes), len(closes) - 1))

    def test_slow_rise_below_threshold_fails(self):
        closes = [100 * 1.002 ** i for i in range(160)]                     # 60일 +13%
        self.assertIsNone(evaluate(bars(closes), len(closes) - 1))


if __name__ == "__main__":
    unittest.main()

"""가파른 추세 판정 — 고르게 오른 상승만 통과하고, 한 번 튄 급등·횡보는 걸러진다."""
import unittest

from pipeline.trend_leaders import evaluate, high_52w, volume_node_retest


def bars(closes, volumes=None):
    return [{"date": f"d{i:04d}", "high": c * 1.01, "low": c * 0.99, "close": c, "volume": (volumes or [1] * len(closes))[i]}
            for i, c in enumerate(closes)]


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


    def test_evidence_has_values_and_fit_line(self):
        closes = [100.0] * 80 + [100 * 1.006 ** i for i in range(1, 81)]
        ev = evaluate(bars(closes), len(closes) - 1)["evidence"]
        self.assertGreater(ev["close"], ev["ma20"])
        self.assertGreater(ev["ma20"], ev["ma60"])
        self.assertGreater(ev["plus_di"], ev["minus_di"])
        self.assertAlmostEqual(ev["fit_end"] / ev["fit_start"], 1.006 ** 60, places=2)


class EventTests(unittest.TestCase):
    def test_52w_high_breakout_in_last_days(self):
        closes = [100.0] * 260 + [99.0, 103.0, 104.0]            # 직전 250일 최고가 101(고가) 돌파
        e = high_52w(bars(closes))
        self.assertEqual((e["kind"], e["date"]), ("high52", "d0261"))

    def test_no_52w_event_when_breakout_is_old(self):
        closes = [100.0] * 255 + [110.0] * 15
        self.assertIsNone(high_52w(bars(closes)))

    def test_volume_node_breakout_then_support(self):
        base = [100.0] * 200 + [80.0] * 50                       # 100 근처가 최대 매물대
        recent = [95.0] * 10 + [104.0, 106.0, 101.5, 105.0, 107.0] + [107.0] * 5
        closes = base + recent + [108.0]
        vols = [10] * 200 + [1] * 50 + [1] * (len(closes) - 250)
        rows = bars(closes, vols)
        rows[-8]["low"] = 100.5                                   # 되돌림 저가가 선 근처에서 멈춤
        e = volume_node_retest(rows)
        self.assertIsNotNone(e)
        self.assertEqual(e["kind"], "vp_retest")

    def test_volume_node_broken_back_below_fails(self):
        base = [100.0] * 200 + [80.0] * 50
        recent = [95.0] * 10 + [104.0, 106.0, 90.0, 105.0, 107.0] + [107.0] * 5
        closes = base + recent + [108.0]
        vols = [10] * 200 + [1] * 50 + [1] * (len(closes) - 250)
        self.assertIsNone(volume_node_retest(bars(closes, vols)))


if __name__ == "__main__":
    unittest.main()

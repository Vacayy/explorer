"""가파른 추세 판정 — 고르게 오른 상승만 통과하고, 한 번 튄 급등·횡보는 걸러진다."""
import unittest

from pipeline.trend_leaders import evaluate, high52_stage, high_52w, volume_node_retest


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


    def test_high52_breakout_and_retest(self):
        """전고점 100(고가 101) — 최근 5거래일 돌파는 breakout, 돌파 → 돌파선 근처 되돌림 → 재반등은 retest"""
        flat = [100.0] * 260
        self.assertEqual(high52_stage(bars(flat + [98, 99, 103])) ["kind"], "breakout")
        run_up, pullback, rebound = [103, 106, 110, 114, 118], [114, 110, 107, 104, 102], [105, 109, 113]
        got = high52_stage(bars(flat + [98] + run_up + pullback + rebound))
        self.assertEqual(got["kind"], "retest")
        self.assertAlmostEqual(got["level"], 101.0)
        self.assertIn("지지", got["detail"])
        # 되돌림이 돌파선 −3% 아래로 마감하면 지지 실패
        self.assertIsNone(high52_stage(bars(flat + [98] + run_up + [112, 106, 100, 96, 99] + rebound)))
        # 저점 뒤 아직 다시 오르지 않았으면(오늘이 저점) 재반등이 아니다
        self.assertIsNone(high52_stage(bars(flat + [98] + run_up + pullback)))
        # 돌파선까지 되돌리지 않고 계속 오른 종목은 retest가 아니다
        self.assertIsNone(high52_stage(bars(flat + [98] + run_up + [116, 114, 113, 112, 114, 115, 116])))

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

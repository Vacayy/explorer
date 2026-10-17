"""밸류체인 지도 정합성과 시차 측정 — 선행 시차를 맞히고, 위약 기준을 넘어야 통과."""
import unittest

from pipeline.value_chain import EDGES, NODES, downstream, upstream, validate
from pipeline.value_chain_lags import _shift_ym, cross_lag


class MapTests(unittest.TestCase):
    def test_map_is_consistent(self):
        self.assertEqual(validate(), [])

    def test_direction_queries(self):
        self.assertIn(("pcb", "supply"), upstream("ai_odm"))
        self.assertIn(("pcb", "supply"), downstream("ccl"))

    def test_every_korean_link_stock_is_placed(self):
        from pipeline.tw_links import LINKS
        placed = {k for n in NODES for k in n[3]}
        self.assertEqual({link[0] for link in LINKS} - placed, set())


class LagTests(unittest.TestCase):
    def series(self, values, start=(2023, 1)):
        y, m = start
        out = {}
        for v in values:
            out[f"{y}-{m:02d}"] = v
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        return out

    def test_shift(self):
        self.assertEqual(_shift_ym("2026-01", -1), "2025-12")
        self.assertEqual(_shift_ym("2025-11", 3), "2026-02")

    def test_finds_upstream_lead(self):
        import math
        base = [10 * math.sin(i / 2.3) + 3 * math.cos(i / 1.1) for i in range(40)]
        up = self.series(base)
        down = self.series([0, 0] + base[:-2])            # 하류가 2개월 뒤 같은 모양
        r = cross_lag(up, down)
        self.assertEqual(r["best_lag"], 2)
        self.assertGreater(r["corr"], 0.95)


if __name__ == "__main__":
    unittest.main()

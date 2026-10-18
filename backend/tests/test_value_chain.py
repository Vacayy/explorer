"""밸류체인 지도 정합성과 시차 측정 — 선행 시차를 맞히고, 위약 기준을 넘어야 통과."""
import unittest

from pipeline.value_chain import EDGES, NODES, downstream, upstream, validate
from pipeline.value_chain_lags import _shift_ym, cross_lag


class MapTests(unittest.TestCase):
    def test_map_is_consistent(self):
        self.assertEqual(validate(), [])

    def test_every_node_has_a_swimlane_cell(self):
        from pipeline.value_chain import validate_layout
        self.assertEqual(validate_layout(), [])

    def test_money_flows_left_to_right(self):
        """돈의 흐름(사는 쪽 → 파는 쪽)으로 그리면 사는 쪽 단계가 파는 쪽보다 왼쪽이거나 같아야 한다"""
        from pipeline.value_chain import LAYOUT, TIERS
        order = {t: i for i, (t, _) in enumerate(TIERS)}
        back = [(a, b) for a, b, _, _ in EDGES if order[LAYOUT[b][0]] > order[LAYOUT[a][0]]]
        self.assertEqual(back, [])

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


class PropagationTests(unittest.TestCase):
    def test_waiting_diverging_and_leads(self):
        from pipeline.value_chain import propagation
        vmap = {"as_of": "2026-09", "nodes": [
            {"key": "a", "name": "A", "kr": [{"code": "1", "name": "일"}], "state": "가속"},
            {"key": "b", "name": "B", "kr": [{"code": "2", "name": "이"}], "state": "유지"},
            {"key": "c", "name": "C", "kr": [], "state": "가속"}],
            "edges": [{"from": "a", "to": "b", "verdict": "확인", "lag": 3, "lag_consistent": True},
                      {"from": "c", "to": "b", "verdict": "확인", "lag": 1, "lag_consistent": True},      # 1개월은 경보 아님
                      {"from": "b", "to": "c", "verdict": "미확인", "lag": 4, "lag_consistent": True}]}   # 미확인은 제외
        confirms = [
            {"stock_code": "1", "directions": {"taiwan": "up", "trade": None, "disclosure": "flat"}, "agree_up": 1, "observed": 2},
            {"stock_code": "2", "directions": {"taiwan": "up", "trade": "down", "disclosure": "up"}, "agree_up": 2, "observed": 3}]
        p = propagation(vmap, confirms)
        self.assertEqual([w["stock_code"] for w in p["waiting"]], ["1"])
        self.assertEqual([w["stock_code"] for w in p["diverging"]], ["2"])
        self.assertEqual(len(p["leads"]), 1)
        self.assertEqual((p["leads"][0]["leader"], p["leads"][0]["follower"], p["leads"][0]["status"]), ("a", "b", "대기"))

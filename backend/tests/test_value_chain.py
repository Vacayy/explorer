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

    def test_node_observation_matches_attached_stocks(self):
        """칸의 주가(한국 종목)와 칸의 관측이 같은 회사들이어야 한다 — 삼성·SK 메모리를 대만 메모리 3사로 판정하던 오류(2026-10-18)"""
        from pipeline.value_chain import KR_OBS
        by = {n[0]: n for n in NODES}
        self.assertIn("memory", KR_OBS)
        self.assertEqual(by["memory"][2], [])
        self.assertEqual(set(by["tw_memory"][2]), {"2408", "2344", "2337"})
        self.assertNotIn("005930", by["foundry"][3])     # 주가가 두 칸에 중복 반영되지 않게


class RelativeStateTests(unittest.TestCase):
    """칸 자기 이력 대비 상태 — 호황기에 ±10%p 고정 기준이 대부분 칸을 '가속'으로 만들던 문제(2026-10-18)"""

    def hist(self, values):
        out, y, m = {}, 2020, 1
        for v in values:
            out[f"{y}-{m:02d}"] = v
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        return out

    def test_big_level_with_usual_swing_is_steady(self):
        from pipeline.value_chain import relative_state
        import math
        vals = [300 + 40 * math.sin(i * 1.3) for i in range(40)] + [310]   # +260~+340%를 늘 오가는 칸 — 10%p 넘는 변화도 평소 수준
        state, z = relative_state(self.hist(vals))
        self.assertEqual(state, "유지")
        self.assertLess(abs(z), 1)

    def test_unusual_jump_is_acceleration(self):
        from pipeline.value_chain import relative_state
        vals = [10 + (1 if i % 2 else -1) for i in range(40)] + [40]
        self.assertEqual(relative_state(self.hist(vals))[0], "가속")

    def test_sign_change_and_short_history(self):
        from pipeline.value_chain import relative_state
        vals = [5 + (1 if i % 2 else -1) for i in range(40)] + [-3]
        self.assertEqual(relative_state(self.hist(vals))[0], "전환↓")
        self.assertEqual(relative_state(self.hist([1, 2, 3, 4, 5])), (None, None))


class KrSeriesTests(unittest.TestCase):
    def test_kr_yoy3m_from_exports(self):
        import sqlite3
        from pipeline.value_chain_lags import kr_quarterly_yoy, kr_yoy3m
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE trade_stats (hs_code, period, export_usd)")
        rows = [("A", f"{y}-{m:02d}", 100.0 if y == 2024 else 150.0) for y in (2024, 2025) for m in range(1, 13)]
        rows += [("B", f"{y}-{m:02d}", 10.0) for y in (2024, 2025) for m in range(1, 13)]
        conn.executemany("INSERT INTO trade_stats VALUES (?,?,?)", rows)
        s = kr_yoy3m(conn, ["A", "B"])
        self.assertAlmostEqual(s["2025-03"], (160 / 110 - 1) * 100)
        self.assertNotIn("2024-12", s)                  # 전년이 없는 달은 내지 않는다
        self.assertAlmostEqual(kr_quarterly_yoy(conn, ["A"])["2025-06"], 50.0)


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

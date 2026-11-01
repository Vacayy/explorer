"""돈의 흐름 — 조용한 가속은 스포트라이트, 주목받는 가속·약한 주가는 의심, 둔화·높은 관심은 식는 칸."""
import unittest
from unittest.mock import patch

from pipeline import value_chain_flow as f


class FlowTests(unittest.TestCase):
    def test_lists(self):
        vmap = {"as_of": "2026-09", "nodes": [
            {"key": "a", "state": "가속", "yoy_3m": 50, "aux": [], "kr": [{"code": "1", "name": "일"}]},
            {"key": "b", "state": "가속", "yoy_3m": 40, "aux": [], "kr": [{"code": "2", "name": "이"}]},
            {"key": "c", "state": "둔화", "yoy_3m": 5, "aux": [], "kr": [{"code": "3", "name": "삼"}]}]}
        nodes = [("a", "A", ["x"], ["1"], ""), ("b", "B", ["x"], ["2"], ""), ("c", "C", ["x"], ["3"], "")]
        ret = {"1": -10.0, "2": -5.0, "3": 30.0}
        att = {"1": (2, 3), "2": (100, 120), "3": (50, 10)}
        with patch("pipeline.value_chain.NODES", nodes), patch("pipeline.value_chain.US_OBS", {}), patch("pipeline.value_chain.KR_OBS", {}), \
                patch.object(f, "_tw_increment", return_value=(1e9, "2026-09")), \
                patch.object(f, "_kr_return", side_effect=lambda conn, codes: ret[codes[0]]), \
                patch.object(f, "_attention", side_effect=lambda conn, codes: att[codes[0]]), \
                patch("database.get_connection"):
            r = f.compute(vmap)
        self.assertEqual([s["key"] for s in r["spotlight"]], ["a"])     # 조용한 가속 + 약한 주가
        self.assertEqual([s["key"] for s in r["doubted"]], ["b"])       # 이미 주목받는데 약한 주가
        self.assertEqual([s["key"] for s in r["fading"]], ["c"])        # 둔화 + 관심 증가
        self.assertTrue(r["spotlight"][0]["falsifier"])


if __name__ == "__main__":
    unittest.main()

"""트리 보고서 — 트리 고르기(LLM 0): 수요 방향(bottom-up), 추정 증가액 큰 가지 우선, 직접 판로 보존, 깊이·칸 상한, 중복 없음."""
import unittest

from pipeline.chain_report import select_tree
from pipeline.value_chain import EDGES, NODES, DEMANDS


def vmap():
    return {"nodes": [{"key": k, "name": n} for k, n, *_ in NODES], "demands": [{"key": k, "name": n} for k, n, _ in DEMANDS]}


class ChainTreeTests(unittest.TestCase):
    def test_walks_demand_side_bottom_up(self):
        """고른 칸에서 그 칸의 물건을 사는 쪽(수요)으로 올라간다 — parent는 그 칸에 파는 칸"""
        buyers = [b for a, b, *_ in EDGES if a == "memory"]
        flows = [{"from": "memory", "to": b, "flow_usd": 100.0 if b == "ai_accel" else 1.0} for b in buyers]
        tree = select_tree("memory", vmap(), flows)
        self.assertEqual(tree[0]["key"], "memory")
        self.assertEqual(tree[1]["key"], "ai_accel")                  # 가장 큰 가지 먼저
        edges = {(a, b) for a, b, *_ in EDGES}
        self.assertTrue(all(t["parent"] is None or (t["parent"], t["key"]) in edges for t in tree))

    def test_every_direct_buyer_is_kept(self):
        """증가액 큰 가지가 칸 상한을 다 차지해도 루트가 직접 파는 칸은 모두 남는다(식각 장비 → 파운드리)"""
        buyers = {b for a, b, *_ in EDGES if a == "kr_etch_clean"}
        flows = [{"from": a, "to": b, "flow_usd": 1000.0} for a, b, *_ in EDGES if a == "memory"]
        tree = select_tree("kr_etch_clean", vmap(), flows)
        self.assertTrue(buyers <= {t["key"] for t in tree})

    def test_caps_and_no_duplicates(self):
        tree = select_tree("memory", vmap(), [], depth=4, max_nodes=12)
        keys = [t["key"] for t in tree]
        self.assertLessEqual(len(tree), 12)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(t["depth"] <= 4 for t in tree))

    def test_children_follow_their_parent(self):
        """들여쓰기로 부모를 읽으므로 자식은 부모 바로 아래 묶여 있어야 한다(꺼낸 순서면 오독)"""
        tree = select_tree("memory", vmap(), [])
        pos = {t["key"]: i for i, t in enumerate(tree)}
        for i, t in enumerate(tree):
            if t["parent"]:
                self.assertLess(pos[t["parent"]], i)
                between = tree[pos[t["parent"]] + 1:i]
                self.assertTrue(all(b["depth"] > tree[pos[t["parent"]]]["depth"] for b in between))


if __name__ == "__main__":
    unittest.main()

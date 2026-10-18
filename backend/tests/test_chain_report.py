"""트리 보고서 — 트리 고르기(LLM 0): 공급 방향, 추정 증가액 큰 가지 우선, 깊이·칸 상한, 중복 없음."""
import unittest

from pipeline.chain_report import select_tree
from pipeline.value_chain import EDGES, NODES, DEMANDS


def vmap():
    return {"nodes": [{"key": k, "name": n} for k, n, *_ in NODES], "demands": [{"key": k, "name": n} for k, n, _ in DEMANDS]}


class ChainTreeTests(unittest.TestCase):
    def test_walks_supply_side_with_biggest_flow_first(self):
        sellers_of_ai = [a for a, b, *_ in EDGES if b == "ai"]
        flows = [{"from": a, "to": "ai", "flow_usd": 100.0 if a == "dc_switch" else 1.0} for a in sellers_of_ai]
        tree = select_tree("ai", vmap(), flows)
        self.assertEqual(tree[0]["key"], "ai")
        self.assertEqual(tree[1]["key"], "dc_switch")                 # 가장 큰 가지 먼저
        self.assertTrue(all(t["parent"] is None or (t["key"], t["parent"]) in {(a, b) for a, b, *_ in EDGES} for t in tree))

    def test_caps_and_no_duplicates(self):
        tree = select_tree("ai", vmap(), [], depth=3, max_nodes=12)
        keys = [t["key"] for t in tree]
        self.assertLessEqual(len(tree), 12)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(t["depth"] <= 3 for t in tree))

    def test_children_follow_their_parent(self):
        """들여쓰기로 부모를 읽으므로 자식은 부모 바로 아래 묶여 있어야 한다(꺼낸 순서면 오독)"""
        tree = select_tree("ai", vmap(), [])
        pos = {t["key"]: i for i, t in enumerate(tree)}
        for i, t in enumerate(tree):
            if t["parent"]:
                self.assertLess(pos[t["parent"]], i)
                between = tree[pos[t["parent"]] + 1:i]
                self.assertTrue(all(b["depth"] > tree[pos[t["parent"]]]["depth"] for b in between))


if __name__ == "__main__":
    unittest.main()

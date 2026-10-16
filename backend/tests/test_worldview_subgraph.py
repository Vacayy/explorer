"""세계관 그래프 규모 대응(D-211): 일괄 쿼리 결과 동일성, 핵심·이웃 부분 그래프, 검색 목록."""
import sqlite3
import unittest

from pipeline.narrative_graph import core_subgraph, full_causal_graph, neighborhood, node_index


def db():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, meta_json TEXT);
        CREATE TABLE entity_relations(id INTEGER PRIMARY KEY, src_id INTEGER, dst_id INTEGER, rel_type TEXT,
            mechanism TEXT, reference_period TEXT, time_orientation TEXT, confidence REAL, effect_direction TEXT,
            effect_strength TEXT, promoted_knowledge_id INTEGER, feedback_note TEXT, geo_scope TEXT,
            source_status TEXT, source_doc_id INTEGER);
        CREATE TABLE narrative_edge_evidence(id INTEGER PRIMARY KEY, entity_relation_id INTEGER, narrative_id INTEGER);
        CREATE TABLE narratives(id INTEGER PRIMARY KEY, category TEXT);
    """)
    # 허브 1 — 2,3,4,5 / 2→6→7 사슬 / 1↔2 역방향(상충), 3→1은 피드백 메모로 해소
    layers = {1: "cycle", 2: "regime", 3: "event", 4: "event", 5: "structure", 6: "flow", 7: "event"}
    c.executemany("INSERT INTO entities VALUES (?,?,?,?)",
                  [(i, "macro", f"n{i}", f'{{"pace_layer": "{l}"}}') for i, l in layers.items()])
    edges = [(1, 1, 2, "CAUSES", None), (2, 1, 3, "CAUSES", None), (3, 1, 4, "CAUSES", None),
             (4, 1, 5, "BENEFITS_FROM", None), (5, 2, 6, "CAUSES", None), (6, 6, 7, "CAUSES", None),
             (7, 2, 1, "CAUSES", None), (8, 3, 1, "CAUSES", "시점 다른 나선")]
    c.executemany("INSERT INTO entity_relations (id, src_id, dst_id, rel_type, feedback_note) VALUES (?,?,?,?,?)", edges)
    c.executemany("INSERT INTO narrative_edge_evidence (entity_relation_id, narrative_id) VALUES (?,?)",
                  [(1, 10), (1, 11), (1, 11), (5, 10)])
    return c


class WorldviewSubgraph(unittest.TestCase):
    def setUp(self):
        self.c = db()

    def test_bulk_corroboration_and_contested(self):
        e = {x["id"]: x for x in full_causal_graph(self.c)["edges"]}
        self.assertEqual(e[1]["corroborated_by"], 2)        # 같은 내러티브 중복은 한 번
        self.assertEqual(e[3]["corroborated_by"], 0)
        self.assertTrue(e[1]["contested"] and e[7]["contested"])   # 1→2, 2→1
        self.assertTrue(e[2]["contested"])                  # 1→3: 역방향 3→1이 있고 자기 메모 없음
        self.assertFalse(e[8]["contested"])                 # 3→1: 자기 피드백 메모가 있으면 상충 아님(D-029)
        self.assertFalse(e[4]["contested"])                 # BENEFITS_FROM은 상충 판정 안 함

    def test_core_ranks_by_degree_then_slow_layer(self):
        g = core_subgraph(self.c, limit=2)
        self.assertEqual({n["id"] for n in g["nodes"]}, {1, 2})   # 차수 6, 3
        self.assertEqual((g["total_nodes"], g["truncated"]), (7, True))
        self.assertTrue(all(e["from_id"] in (1, 2) and e["to_id"] in (1, 2) for e in g["edges"]))
        g3 = core_subgraph(self.c, limit=3)                       # 차수 2 동률(3·6) → 느린 층(flow) 6 먼저
        self.assertIn(6, {n["id"] for n in g3["nodes"]})

    def test_neighborhood_hops_and_limit(self):
        self.assertEqual({n["id"] for n in neighborhood(self.c, 6, depth=1)["nodes"]}, {6, 2, 7})
        self.assertEqual({n["id"] for n in neighborhood(self.c, 6, depth=2)["nodes"]}, {6, 2, 7, 1})
        g = neighborhood(self.c, 1, depth=2, limit=3)
        self.assertTrue(g["truncated"]); self.assertEqual(len(g["nodes"]), 3)
        self.assertIn(2, {n["id"] for n in g["nodes"]})          # 같은 홉은 연결 수 순
        self.assertIsNone(neighborhood(self.c, 999))

    def test_index_is_light(self):
        idx = {x["id"]: x for x in node_index(self.c)}
        self.assertEqual(set(idx[1]), {"id", "name", "type", "pace_layer", "degree"})
        self.assertEqual(idx[1]["degree"], 6)


if __name__ == "__main__":
    unittest.main()

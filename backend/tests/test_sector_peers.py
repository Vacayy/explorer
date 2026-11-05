"""산업·섹터 → Peer 그룹 대응표 (ia-redesign §4.12, D-301 6).

- 초안은 표가 비었을 때 한 번만 심는다(다시 init해도 그대로, 지운 행을 되살리지 않는다).
- share = 그룹 구성 종목 중 그 섹터 비율(섹터를 모르는 종목은 분모에서 뺀다).
- 자동 제안: 연결 없는 섹터에만, share ≥ 0.6 · 그 섹터 종목 2개 이상 · 아직 어느 섹터에도 걸리지 않은 그룹.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from pipeline import sector_peers as sp
from routers.peers import DATA, read_runtime


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()

    def rows(self):
        conn = database.get_connection()
        try:
            return conn.execute("SELECT sector, peer_group_id, partial, note, source FROM sector_peer_map ORDER BY sector, sort").fetchall()
        finally:
            conn.close()

    def test_seed_once_and_idempotent(self):
        first = self.rows()
        self.assertEqual(len(first), sum(len(e["groups"]) for e in sp.SEED))
        self.assertTrue(all(r["source"] == "seed" for r in first))
        partial = {r["sector"] for r in first if r["partial"]}
        self.assertEqual(partial, {"유통·소비재", "건설·부동산", "기계·장비", "화학·소재"})
        database.init_db()
        self.assertEqual([tuple(r) for r in self.rows()], [tuple(r) for r in first])
        conn = database.get_connection()
        conn.execute("DELETE FROM sector_peer_map WHERE peer_group_id = 'nuclear_epc'")
        conn.commit()
        self.assertEqual(sp.seed(conn), 0, "a non-empty table is not re-seeded")
        conn.close()
        self.assertEqual(len(self.rows()), len(first) - 1)


class BuildTests(unittest.TestCase):
    GROUPS = [{"id": "chain", "name": "반도체 밸류체인", "scope": "value_chain"}, {"id": "memory", "name": "메모리", "scope": "product"},
              {"id": "bio", "name": "바이오 CDMO", "scope": "product"}, {"id": "auto", "name": "완성차", "scope": "product"},
              {"id": "solo", "name": "한 종목", "scope": "product"}, {"id": "equip", "name": "장비", "scope": "product"}]
    MEMBERS = {"chain": ["a", "b", "c", "d", "x"], "memory": ["a", "b"], "equip": ["c", "d"], "bio": ["p", "q", "r", "s", "z"],
               "auto": ["m", "n", "o", "p", "q"], "solo": ["t"]}
    SECTOR_OF = {"a": "반도체", "b": "반도체", "c": "기계", "d": "기계", "p": "바이오", "q": "바이오", "r": "바이오", "s": "화학",
                 "m": "자동차", "n": "자동차", "o": "화학", "t": "통신"}   # x·z = 섹터 모름
    ROWS = [{"sector": "반도체", "peer_group_id": "chain", "sort": 0, "partial": 0, "note": None, "source": "seed"},
            {"sector": "반도체", "peer_group_id": "gone", "sort": 1, "partial": 0, "note": None, "source": "seed"}]

    def build(self):
        out = sp.build(["기계", "바이오", "반도체", "자동차", "통신"], self.ROWS, self.GROUPS, self.MEMBERS, self.SECTOR_OF)
        return {s["sector"]: s for s in out}

    def test_share_excludes_unclassified_members_and_drops_unknown_groups(self):
        semi = self.build()["반도체"]
        self.assertEqual([l["group_id"] for l in semi["links"]], ["chain"], "group ids missing from the catalog are dropped")
        link = semi["links"][0]
        self.assertEqual((link["members"], link["classified"], link["in_sector"], link["share"], link["source"]), (5, 4, 2, 0.5, "seed"))

    def test_auto_suggest_threshold_and_exclusions(self):
        out = self.build()
        bio = out["바이오"]["links"]
        self.assertEqual([(l["group_id"], l["source"], l["share"]) for l in bio], [("bio", "auto", 0.75)], "3/4 classified ≥ 0.6")
        self.assertEqual(out["자동차"]["links"], [], "2/5 = 0.4 is below the threshold")
        self.assertEqual(out["통신"]["links"], [], "a single company is not enough")
        self.assertEqual(out["기계"]["links"], [], "equip (2/2 in 기계) sits inside the linked chain, so it is already covered")

    def test_threshold_is_inclusive(self):
        members = {"g": ["a", "b", "c", "d", "e"]}
        sector_of = {"a": "S", "b": "S", "c": "S", "d": "T", "e": "T"}
        out = sp.build(["S"], [], [{"id": "g", "name": "G", "scope": "product"}], members, sector_of)
        self.assertEqual(out[0]["links"][0]["share"], 0.6)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        patch("routers.peers.read_runtime", lambda: read_runtime(root=Path(self.tmp.name) / "none", data=DATA)).start()
        self.addCleanup(patch.stopall)
        database.init_db()
        conn = database.get_connection()
        conn.executemany("INSERT INTO sector_map (sector_name, group_name) VALUES (?, ?)",
                         [("반도체 제조업", "반도체·전자부품"), ("화장품 제조업", "화학·소재"), ("통신업", "통신")])
        conn.execute("INSERT INTO entities (id, type, name, status) VALUES (1, 'sector', '반도체 제조업', 'active')")
        conn.execute("INSERT INTO entities (id, type, name, aliases, status) VALUES (2, 'company', 'SK하이닉스', '000660', 'active')")
        conn.execute("INSERT INTO entity_relations (src_id, dst_id, rel_type) VALUES (2, 1, 'MEMBER_OF')")
        conn.commit()
        conn.close()

    def test_returns_every_sector_with_links_and_shares(self):
        r = TestClient(app).get("/api/spine/sector-map/peers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([s["sector"] for s in body["sectors"]], ["반도체·전자부품", "통신", "화학·소재"])
        semi = body["sectors"][0]["links"][0]
        self.assertEqual((semi["group_id"], semi["source"], semi["classified"], semi["in_sector"], semi["share"]),
                         ("semiconductor_value_chain", "seed", 1, 1, 1.0))
        chem = body["sectors"][2]
        self.assertTrue(chem["partial"])
        self.assertEqual(chem["note"], "반도체 소재 중심")


if __name__ == "__main__":
    unittest.main()

"""인물 디렉토리 — 단일 집계(N+1 제거)·7일 급상승 정렬·롱테일 숨김, 도시에의 인과 엣지·프로필 이후 새 언급.

디렉토리는 인물마다 상관 서브쿼리 2개를 돌아 실제 DB에서 20초·920KB였다(조사 D).
"""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routers import spine_person
from tests.test_job_status import KeepOpen


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class PersonDirectoryTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.executescript("""
            CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT, type TEXT, aliases TEXT);
            CREATE TABLE entity_links(doc_id INT, entity_id INT, link_type TEXT, UNIQUE(doc_id, entity_id, link_type));
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT, published_at TEXT, fetched_at TEXT, markdown TEXT);
            CREATE TABLE follows(entity_id INT UNIQUE);
            CREATE TABLE source_digests(kind TEXT, key TEXT, digest TEXT, insights TEXT, doc_count INT, doc_ids_hash TEXT, created_at TEXT);
            CREATE TABLE narratives(id INTEGER PRIMARY KEY, topic TEXT, version INT, title TEXT, superseded_at TEXT);
            CREATE TABLE entity_relations(id INTEGER PRIMARY KEY, src_id INT, dst_id INT, rel_type TEXT, epistemic_type TEXT,
                mechanism TEXT, narrative_id INT, created_at TEXT);
            INSERT INTO entities VALUES (1,'젠슨 황','person',NULL), (2,'트럼프','person',NULL), (3,'한번만','person',NULL),
                                        (4,'팔로우롱테일','person',NULL), (10,'엔비디아','company','NVDA'), (11,'AI HW 수요','theme',NULL);
            INSERT INTO follows VALUES (4);
        """)
        docs, links = [], []
        # 젠슨 황: 이번 주 3, 지난주 0 (Δ +3) / 트럼프: 이번 주 2, 지난주 4 (Δ −2), 누적은 트럼프가 많다
        plan = [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 9), (2, 10), (2, 11), (2, 12), (2, 30), (3, 1), (4, 40)]
        for i, (pid, d) in enumerate(plan, start=100):
            docs.append((i, f"doc{i}", ago(d), ago(d).replace("T", " ")[:19]))
            links.append((i, pid, "person"))
        links += [(100, 10, "stock"), (101, 10, "stock")]
        raw.executemany("INSERT INTO raw_documents(id, title, published_at, fetched_at) VALUES (?,?,?,?)", docs)
        raw.executemany("INSERT INTO entity_links VALUES (?,?,?)", links)
        self.conn = KeepOpen(raw)
        self.client = TestClient(app)

    def get(self, path):
        with patch.object(spine_person, "get_connection", return_value=self.conn):
            return self.client.get(path).json()

    def test_default_is_surge_and_hides_one_mention_tail_except_followed(self):
        d = self.get("/api/spine/person")
        self.assertEqual([r["name"] for r in d["items"]], ["젠슨 황", "팔로우롱테일", "트럼프"])   # Δ +3 > 0 > −2
        self.assertEqual((d["total"], d["hidden_tail"]), (4, 1))
        j = d["items"][0]
        self.assertEqual((j["mentions_7d"], j["mentions_prev_7d"], j["delta_7d"]), (3, 0, 3))
        self.assertEqual(j["top_stocks"], ["엔비디아"])
        self.assertEqual(j["last_doc_id"], 100)
        self.assertEqual(d["items"][2]["delta_7d"], -2)

    def test_total_sort_and_tail_toggle(self):
        d = self.get("/api/spine/person?sort=total&min_mentions=1")
        self.assertEqual([r["name"] for r in d["items"]][:2], ["트럼프", "젠슨 황"])
        self.assertEqual(d["hidden_tail"], 0)

    def test_window_keeps_week_delta(self):
        d = self.get("/api/spine/person?days=7&min_mentions=1")
        tr = next(r for r in d["items"] if r["name"] == "트럼프")
        self.assertEqual((tr["doc_count"], tr["mentions_prev_7d"]), (2, 4))   # 창 밖 직전 7일도 센다

    def test_followed_week(self):
        d = self.get("/api/spine/person/followed")
        self.assertEqual([r["name"] for r in d["items"]], ["팔로우롱테일"])
        self.assertEqual(d["items"][0]["mentions_7d"], 0)

    def test_dossier_relations_and_new_since_profile(self):
        self.conn.executescript("""
            INSERT INTO narratives VALUES (1, '데이터센터', 1, '옛 제목', '2026-10-01'), (2, '데이터센터', 2, '새 제목', NULL);
            INSERT INTO entity_relations VALUES (1, 1, 11, 'CAUSES', 'hypothesis', '공격적 구축 기조', 1, '2026-09-01');
        """)
        self.conn.execute("INSERT INTO source_digests VALUES ('person','젠슨 황','d',NULL,1,'x',?)", (ago(2.5).replace("T", " ")[:19],))
        d = self.get("/api/spine/person/" + "젠슨 황" + "/dossier")
        self.assertEqual(d["new_since_profile"], 2)
        rel = d["relations"][0]
        self.assertEqual((rel["direction"], rel["other_name"], rel["narrative_topic"], rel["narrative_title"]),
                         ("out", "AI HW 수요", "데이터센터", "새 제목"))
        self.assertTrue(rel["narrative_superseded"])


if __name__ == "__main__":
    unittest.main()

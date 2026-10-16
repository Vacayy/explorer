"""포트폴리오 공통 변수 (portfolio-intelligence §1). 가상 데이터."""
import sqlite3
import unittest

from pipeline import portfolio_exposure as px


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE entities (id INTEGER PRIMARY KEY, type TEXT, name TEXT, aliases TEXT);
        CREATE TABLE entity_relations (src_id INT, dst_id INT, rel_type TEXT, confidence REAL, effect_direction TEXT, source_status TEXT);
        CREATE TABLE entity_links (doc_id INT, entity_id INT, link_type TEXT);
        CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, published_at TEXT);
        CREATE TABLE value_chains (group_name TEXT, stage_idx INT, stage_name TEXT, themes_json TEXT);
        CREATE TABLE industry_members (stock_code TEXT, category TEXT);
        INSERT INTO entities VALUES (1,'company','가','000001'),(2,'company','나','000002'),
          (10,'sector','HBM',''),(11,'theme','수급',''),(12,'sector','바이오',''),(13,'theme','메모리 가격',''),(14,'theme','소문',''),
          (20,'event','나 수주 급증','');
        INSERT INTO entity_relations VALUES (13,1,'CAUSES',0.6,'positive','document'),(14,1,'CAUSES',0.9,'positive','legacy_unverified'),
          (13,20,'CAUSES',0.5,'negative','verified'),(1,10,'BENEFITS_FROM',0.7,'positive','document');
        INSERT INTO value_chains VALUES ('반도체',0,'장비 (전공정)','["HBM"]'),('반도체',1,'제조 (메모리)','["DRAM"]'),('유통',0,'제조·수탁','["화장품"]');
        INSERT INTO industry_members VALUES ('000001','제조·종합');
    """)
    return c


def link(c, doc, *ents):
    c.execute("INSERT OR IGNORE INTO raw_documents VALUES (?, datetime('now'))", (doc,))
    for e, t in ents:
        c.execute("INSERT INTO entity_links VALUES (?,?,?)", (doc, e, t))


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.c = db()
        for d in range(1, 5):                               # 가·나 둘 다 HBM 문서 4건(종목 1~2개짜리)
            link(self.c, d, (1, "stock"), (2, "stock"), (10, "industry"), (11, "topic"))
        for d in range(5, 9):                               # 나가 30종목 나열 시황 글에서만 '바이오'
            link(self.c, d, (2, "stock"), (12, "industry"), *[(100 + k, "stock") for k in range(30)])
        for d in range(100, 140):                           # 배경 문서(기저율)
            link(self.c, d, (999, "topic"))

    def test_graph_uses_evidenced_edges_events_and_benefits(self):
        g = px.graph_drivers(self.c, "000001")
        self.assertEqual(set(g), {13, 10})                   # legacy_unverified '소문' 제외, BENEFITS_FROM은 역방향 동인
        self.assertEqual(g[13]["sign"], 1)
        self.assertEqual(px.graph_drivers(self.c, "000002")[13]["sign"], -1)   # '나 수주 급증' 사건 노드로 연결

    def test_comention_downweights_market_wraps_and_genre_tags(self):
        cm = px.comention_drivers(self.c, "000002")
        self.assertIn(10, cm)
        self.assertNotIn(11, cm)                             # '수급'은 글 성격 태그
        self.assertNotIn(12, cm)                             # 30종목 나열 글의 '바이오'는 가중치가 작다

    def test_chain_requires_thematic_evidence(self):
        self.assertEqual(px.chain_stage(self.c, "000001", {"HBM"}), ("반도체", "제조 (메모리)"))
        self.assertIsNone(px.chain_stage(self.c, "000001", set()))   # 분류 이름 '제조'만으로 유통 체인에 붙지 않음

    def test_exposure_merges_and_weights(self):
        r = px.exposure(self.c, [{"code": "000001", "name": "가", "weight_pct": 60}, {"code": "000002", "name": "나", "weight_pct": 40}])
        by = {d["name"]: d for d in r["drivers"]}
        self.assertEqual(by["메모리 가격"]["exposure_pct"], 100.0)
        self.assertEqual(by["메모리 가격"]["direction"], "+−")
        self.assertEqual(by["HBM"]["sources"], ["comention", "graph"])


if __name__ == "__main__":
    unittest.main()

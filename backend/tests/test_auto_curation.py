"""정리 작업 자동 처리(D-294): 별칭·노드 병합·지식 승격 규칙 판정과 드라이런/적용 구분."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import auto_curation as ac

SCHEMA = """
CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, aliases TEXT, meta_json TEXT, status TEXT DEFAULT 'active', created_at TEXT);
CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY, entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE, keyword TEXT, status TEXT DEFAULT 'active', created_at TEXT, UNIQUE(entity_id, keyword));
CREATE TABLE entity_links(doc_id INTEGER, entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE, link_type TEXT, confidence REAL, UNIQUE(doc_id, entity_id, link_type));
CREATE TABLE entity_relations(id INTEGER PRIMARY KEY, src_id INTEGER, dst_id INTEGER, rel_type TEXT, valid_from TEXT, confidence REAL,
  mechanism TEXT, reference_period TEXT, time_orientation TEXT, feedback_note TEXT, promoted_knowledge_id INTEGER, narrative_id INTEGER);
CREATE TABLE narrative_edge_evidence(entity_relation_id INTEGER, narrative_id INTEGER);
CREATE TABLE entity_merges(id INTEGER PRIMARY KEY, old_name TEXT, type TEXT, survivor_id INTEGER, rationale TEXT, merged_at TEXT, UNIQUE(old_name, type));
CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT, markdown TEXT);
CREATE TABLE agent_proposals(id INTEGER PRIMARY KEY, kind TEXT, title TEXT, rationale TEXT, payload_json TEXT, dedup_key TEXT,
  status TEXT DEFAULT 'proposed', detected_at TEXT, actioned_at TEXT, result_json TEXT);
CREATE TABLE knowledge(id INTEGER PRIMARY KEY, statement TEXT, epistemic_status TEXT, review_status TEXT, created_at TEXT);
CREATE TABLE knowledge_evidence(knowledge_id INTEGER, doc_id INTEGER, stance TEXT, independent INTEGER);
CREATE TABLE curation_log(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target_id INTEGER NOT NULL, verdict TEXT NOT NULL,
  rule TEXT, applied INTEGER DEFAULT 0, detail_json TEXT, decided_at TEXT DEFAULT (datetime('now')), UNIQUE(kind, target_id));
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.executemany("INSERT INTO entities (id, type, name, aliases) VALUES (?,?,?,?)", [
            (1, "company", "삼성전자", "005930"), (2, "company", "삼성생명", "032830"),
            (3, "company", "LS Electric", "010120"), (4, "company", "KB국민은행", None),
            (5, "company", "두산에너빌리티", "034020"), (6, "company", "두산에너빌리티서비스", "999999"),
            (7, "company", "한화에어로스페이스", "012450"), (8, "theme", "AI 안전", None), (9, "theme", "AI안전", None),
        ])
        self.conn.executemany("INSERT INTO raw_documents (id, title, markdown) VALUES (?,?,?)", [
            (1, "한화에어로 수주", "한화에어로스페이스가 ..."), (2, "LS ELECTRIC 실적", "전력기기"), (3, "기타", "본문"),
        ])

    def verdict(self, eid, kw):
        return ac.classify_alias(self.conn, eid, kw)[0]


class AliasRules(Base):
    def test_rejects_noise_generic_group_prefix_and_subsidiary(self):
        self.assertEqual(self.verdict(1, "없음"), "reject")
        self.assertEqual(self.verdict(1, "반도체"), "reject")
        self.assertEqual(self.verdict(2, "삼성"), "reject")               # 그룹 접두어 단독 → 한 계열사에 묶지 않음
        self.assertEqual(self.verdict(1, "삼성전자서비스"), "reject")      # 자회사 → 모회사 별칭 아님
        self.assertEqual(self.verdict(1, "기흥 SR5"), "reject")           # 공장
        self.assertEqual(self.verdict(1, "삼전, 삼성전자"), "reject")      # 여러 이름 묶음
        self.assertEqual(self.verdict(1, "삼성전자그룹"), "hold")         # 그룹명 → 같은 이름 회사: 지주/계열사 판단 불가
        self.assertEqual(self.verdict(1, "삼성전자 005930"), "reject")     # 이름+코드

    def test_approves_spacing_case_variants_only_for_coded_entity(self):
        self.assertEqual(self.verdict(3, "LS ELECTRIC"), "approve")
        self.assertEqual(self.verdict(4, "KB 국민은행"), "hold")          # 코드 없는 대상 → 중복 엔티티 가능

    def test_prefix_abbreviation_needs_unique_prefix(self):
        self.assertEqual(self.verdict(7, "한화에어로"), "approve_if_small")
        self.assertEqual(self.verdict(5, "두산에너빌"), "hold")           # 다른 회사 이름도 이 앞부분으로 시작

    def test_collision_with_other_entity_keyword_is_held(self):
        self.conn.execute("INSERT INTO entity_keywords (entity_id, keyword, status) VALUES (2, '한화에어로', 'active')")
        self.assertEqual(self.verdict(7, "한화에어로"), "hold")

    def test_dry_run_logs_without_changing_state_and_apply_links(self):
        self.conn.executemany("INSERT INTO entity_keywords (id, entity_id, keyword, status) VALUES (?,?,?, 'proposed')",
                              [(10, 7, "한화에어로"), (11, 1, "없음"), (12, 4, "국민銀")])
        ac.curate_aliases(self.conn, apply=False)
        self.assertEqual({r["status"] for r in self.conn.execute("SELECT status FROM entity_keywords")}, {"proposed"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM curation_log WHERE applied=0").fetchone()[0], 3)
        stats = ac.curate_aliases(self.conn, apply=True)
        st = {r["id"]: r["status"] for r in self.conn.execute("SELECT id, status FROM entity_keywords")}
        self.assertEqual(st, {10: "active", 11: "rejected", 12: "held"})
        self.assertEqual(stats, {"approve": 1, "reject": 1, "hold": 1})
        self.assertTrue(self.conn.execute("SELECT 1 FROM entity_links WHERE doc_id=1 AND entity_id=7").fetchone())


class MergeRules(Base):
    def test_classify(self):
        self.assertEqual(ac.classify_merge({"survivor_name": "AI 안전", "loser_name": "AI안전", "type": "theme"})[0], "approve")
        self.assertEqual(ac.classify_merge({"survivor_name": "반도체 주가 급락", "loser_name": "반도체 종목 주가 급락",
                                            "type": "event", "cosine": 0.99})[0], "hold")
        self.assertEqual(ac.classify_merge({"survivor_name": "슈나이더 일렉트릭", "loser_name": "슈나이더",
                                            "type": "company", "cosine": 0.98})[0], "hold")
        self.assertEqual(ac.classify_merge({"survivor_name": "Alpha", "loser_name": "알파", "type": "theme", "cosine": 0.975})[0], "approve")
        self.assertEqual(ac.classify_merge({"survivor_name": "Alpha", "loser_name": "알파", "type": "theme", "cosine": 0.93})[0], "hold")

    def test_apply_merges_with_snapshot_and_skips_finished_chain(self):
        self.conn.execute("INSERT INTO entity_links VALUES (3, 9, 'topic', 0.9)")
        p = {"survivor_id": 8, "loser_id": 9, "survivor_name": "AI 안전", "loser_name": "AI안전", "type": "theme"}
        self.conn.execute("INSERT INTO agent_proposals (id, kind, title, payload_json) VALUES (1, 'vocab_merge', 't', ?)", (json.dumps(p),))
        self.conn.execute("INSERT INTO agent_proposals (id, kind, title, payload_json) VALUES (2, 'vocab_merge', 't', ?)", (json.dumps(p),))
        ac.curate_merges(self.conn, apply=True)
        # 생존자 = 링크 많은 쪽(9). 제안의 survivor_id(8)가 아니라 규칙(코드 > 링크 > 낮은 id)으로 고른다
        self.assertIsNone(self.conn.execute("SELECT 1 FROM entities WHERE id=8").fetchone())
        self.assertTrue(self.conn.execute("SELECT 1 FROM entity_links WHERE doc_id=3 AND entity_id=9").fetchone())
        log = json.loads(self.conn.execute("SELECT detail_json FROM curation_log WHERE kind='vocab_merge' AND target_id=1").fetchone()[0])
        self.assertEqual(log["snapshot"]["entity"]["name"], "AI 안전")
        st = dict(self.conn.execute("SELECT id, status FROM agent_proposals").fetchall())
        self.assertEqual(st, {1: "actioned", 2: "dismissed"})


class KnowledgeRules(Base):
    def add(self, kid, stmt, ev):
        self.conn.execute("INSERT INTO knowledge (id, statement, review_status, created_at) VALUES (?,?, 'proposed', ?)", (kid, stmt, kid))
        self.conn.executemany("INSERT INTO knowledge_evidence VALUES (?,?,?,?)", [(kid, i, s, ind) for i, (s, ind) in enumerate(ev)])

    def test_rules_and_daily_budget(self):
        self.add(1, "금리 하락이 성장주 멀티플을 올린다", [])
        self.add(2, "HBM 공급 부족이 2027년까지 이어진다", [("support", 1), ("support", 1)])
        self.add(3, "AI 투자가 전력 수요를 키운다", [("support", 1), ("refute", 0)])
        self.add(4, "원전 수주가 늘어난다", [("support", 1)])
        self.add(5, "HBM 공급 부족이 2027년까지 이어진다", [("support", 1), ("support", 1)])
        with patch("pipeline.falsifiers.generate_falsifiers", return_value=["x"]) as gen:
            ac.curate_knowledge(self.conn, apply=True, cap=5)
        st = dict(self.conn.execute("SELECT id, review_status FROM knowledge").fetchall())
        self.assertEqual(st, {1: "rejected", 2: "active", 3: "held", 4: "held", 5: "rejected"})   # 5는 2와 같은 주장
        self.assertEqual(gen.call_count, 1)

    def test_budget_defers_approvals(self):
        self.add(2, "HBM 공급 부족이 2027년까지 이어진다", [("support", 1), ("support", 1)])
        with patch("pipeline.falsifiers.generate_falsifiers") as gen:
            stats = ac.curate_knowledge(self.conn, apply=True, cap=0)
        self.assertEqual(stats["deferred"], 1)
        gen.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT review_status FROM knowledge WHERE id=2").fetchone()[0], "proposed")


if __name__ == "__main__":
    unittest.main()

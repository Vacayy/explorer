"""월드모델 읽기 전용 API(/api/spine/world/*): 저장분만 읽고 LLM·subprocess를 절대 부르지 않는다.

위젯과 '지금' 랜딩이 열릴 때마다 opus·haiku가 돌면 안 된다(docs/specs/home-widgets.md §2-1).
LLM 진입점을 모두 '기록 후 예외'로 바꿔 두고 실제 init_db 스키마 위에서 각 GET을 부른다.
기존 코드 일부(narrative_diff)는 예외를 삼키므로, 예외가 아니라 호출 기록이 비어 있는지로 판정한다.
"""
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
import pipeline.enrich as enrich
import pipeline.narrative as narrative
from routers import spine_world


CALLS: list[str] = []


def _boom(name):
    def fn(*_a, **_k):
        CALLS.append(name)
        raise AssertionError(f"월드모델 읽기 경로에서 {name} 호출")
    return fn


SEED = """
INSERT INTO entities(id, type, name, aliases) VALUES
  (1, 'company', 'SK하이닉스', '000660'), (2, 'theme', '메모리', NULL), (3, 'sector', '메모리 반도체', NULL),
  (4, 'macro', 'AI 수요', NULL), (5, 'company', '삼성전자', '005930'), (6, 'theme', '반도체', NULL),
  (7, 'company', '무관전자', '999999');
INSERT INTO narratives(id, topic, version, title, body, category, created_at, drift_summary, kind, core_question) VALUES
  (10, '메모리', 1, '옛 제목', 'v1', 'industry', datetime('now', '-20 days'), NULL, 'topic', NULL),
  (11, '메모리', 2, 'AI 증설의 병목은 메모리로', 'v2', 'industry,tech', datetime('now', '-1 day'),
       'AI 수요→메모리 고리가 새로 들어왔다', 'topic', '메모리 부족은 2027년까지 이어질까?'),
  (12, '반도체', 1, '반도체 서사', 'b1', 'industry', datetime('now', '-40 days'), NULL, 'topic', NULL),
  (20, '엮인 큰 그림', 1, '공급망으로 내려온 AI 경쟁', 'mega body', NULL, datetime('now', '-3 days'), NULL, 'mega', NULL);
UPDATE narratives SET members_json='["메모리","반도체"]' WHERE id=20;
-- v1: AI 수요→메모리 반도체 / v2: + SK하이닉스 수혜, 삼성전자→반도체(이웃 경로)
INSERT INTO entity_relations(src_id, dst_id, rel_type, narrative_id, source_status, valid_from, effect_direction) VALUES
  (4, 3, 'CAUSES', 11, 'verified', 'a', 'positive'),
  (1, 4, 'BENEFITS_FROM', 11, 'verified', 'b', 'positive'),
  (5, 6, 'CAUSES', NULL, 'document', 'c', 'positive'),
  (7, 4, 'CAUSES', 11, 'legacy_unverified', 'd', NULL);
INSERT INTO stock_groups(id, name, kind) VALUES (1, '내 포트폴리오', 'portfolio'), (2, '관심', 'watch');
INSERT INTO stock_group_members(group_id, stock_code) VALUES (1, '000660'), (2, '000660'), (2, '005930'), (2, '999999'), (2, '123456');
INSERT INTO questions(id, text, narrative_id, created_by, status) VALUES
  (5, '메모리 부족은 2027년까지 이어질까?', 10, 'system', 'tracking');
INSERT INTO sub_questions(question_id, text, falsifier) VALUES (5, 'DRAM 재고는 줄고 있나', 'DRAM 재고가 2분기 연속 증가');
INSERT INTO raw_documents(id, title, source_type, source_id) VALUES (900, '증설 25% 소식', 'telegram', 't-900');
INSERT INTO knowledge(id, statement, epistemic_status, review_status, pace_layer, contested_at) VALUES
  (1, '메모리 수요가 공급을 크게 웃돈다', 'contested', 'active', 'cycle', '2026-10-01T00:00:00+00:00'),
  (2, '승인 대기 지식', 'contested', 'proposed', 'cycle', NULL);
INSERT INTO knowledge_evidence(knowledge_id, doc_id, stance, independent, observed_at) VALUES
  (1, 900, 'refute', 1, '2026-10-02T00:00:00+00:00'), (1, NULL, 'support', 1, '2026-09-01T00:00:00+00:00');
INSERT INTO source_digests(kind, key, digest, doc_ids_hash, created_at) VALUES
  ('worldview', 'global', '## 자리 잡은 전제', 'old-hash', '2026-10-12 00:00:00');
"""


class WorldReadsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "test.sqlite"
        with patch.object(database, "DB_PATH", path):
            database.init_db()
        c = sqlite3.connect(path)
        c.executescript(SEED)
        c.commit()
        c.close()

        def connection():
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        for target in (patch.object(spine_world, "get_connection", connection),
                       patch.object(enrich, "_call_claude_code", _boom("enrich._call_claude_code")),
                       patch.object(narrative, "_call", _boom("narrative._call")),
                       patch.object(narrative, "llm_engine", lambda: "claude-code"),   # 엔진이 켜져 있어도
                       patch.object(subprocess, "run", _boom("subprocess.run")),
                       patch.object(subprocess, "Popen", _boom("subprocess.Popen"))):
            target.start()
            self.addCleanup(target.stop)
        CALLS.clear()
        self.addCleanup(lambda: self.assertEqual(CALLS, [], "LLM/subprocess가 불렸다"))
        app = FastAPI()
        app.include_router(spine_world.router)
        self.client = TestClient(app)

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_big_picture_reads_mega_and_stored_worldview_without_generating(self):
        d = self.get("/api/spine/world/big-picture")
        self.assertEqual([m["members"] for m in d["mega"]], [["메모리", "반도체"]])
        self.assertEqual(d["worldview"]["briefing"], "## 자리 잡은 전제")
        self.assertTrue(d["worldview"]["stale"])   # 입력 해시가 달라도 생성하지 않고 표시만

    def test_changes_lists_recent_versions_with_deterministic_edge_diff(self):
        d = self.get("/api/spine/world/changes?days=7")
        self.assertEqual([i["topic"] for i in d["items"]], ["메모리"])   # 40일 된 반도체는 빠진다
        item = d["items"][0]
        self.assertEqual(item["drift_summary"], "AI 수요→메모리 고리가 새로 들어왔다")
        self.assertFalse(item["is_first"])
        self.assertEqual(item["added_count"], 3)   # 엣지 태그가 최신 버전(11)에만 있어 v1은 빈 서브그래프
        self.assertIn({"from": "AI 수요", "to": "메모리 반도체", "rel": "CAUSES", "effect_direction": "positive"},
                      item["added_edges"])

    def test_contested_only_active_with_latest_refute_doc(self):
        d = self.get("/api/spine/world/contested")
        self.assertEqual([i["id"] for i in d["items"]], [1])
        self.assertEqual(d["items"][0]["latest_refute"]["title"], "증설 25% 소식")
        self.assertEqual((d["items"][0]["refute"], d["items"][0]["support"]), (1, 1))

    def test_my_stocks_joins_groups_trusted_edges_and_latest_narrative(self):
        d = self.get("/api/spine/world/my-stocks")
        self.assertEqual(d["members"], 4)          # 묶음 종목 4개(중복 제거), 엔티티 없는 123456 포함
        by = {s["stock_code"]: s for s in d["stocks"]}
        self.assertEqual(set(by), {"000660", "005930"})   # 무관전자: 미검증 엣지만 → 제외
        hynix = by["000660"]
        self.assertEqual(sorted(hynix["kinds"]), ["portfolio", "watch"])
        self.assertEqual(hynix["narratives"][0]["topic"], "메모리")
        self.assertEqual(hynix["narratives"][0]["narrative_id"], 11)   # 주제의 최신본
        self.assertEqual(hynix["latest_drift"], "AI 수요→메모리 고리가 새로 들어왔다")
        samsung = by["005930"]["narratives"][0]
        self.assertEqual((samsung["topic"], samsung["via"]), ("반도체", "neighbor"))

    def test_checkpoint_links_tracked_question_falsifiers_beneficiaries_and_my_stocks(self):
        d = self.get("/api/spine/world/checkpoint?topic=메모리")
        self.assertEqual(d["core_question"], "메모리 부족은 2027년까지 이어질까?")
        self.assertEqual(d["question"]["id"], 5)   # 이전 버전에서 도출된 추적 질문도 찾는다
        self.assertEqual([f["condition"] for f in d["falsifiers"]], ["DRAM 재고가 2분기 연속 증가"])
        names = {b["name"]: b for b in d["beneficiaries"]}
        self.assertIn("메모리 반도체", names)
        self.assertEqual(names["SK하이닉스"]["stock_code"], "000660")
        self.assertEqual([s["stock_code"] for s in d["my_stocks"]], ["000660"])

    def test_guard_detects_swallowed_llm_call(self):
        """대조군: 캐시 없는 drift 요약은 haiku를 부르고 예외를 삼킨다 — 기록으로는 잡힌다."""
        conn = spine_world.get_connection()
        conn.execute("UPDATE narratives SET drift_summary=NULL WHERE id=11")
        conn.commit()
        narrative.narrative_diff(conn, 11)
        conn.close()
        self.assertEqual(CALLS, ["narrative._call"])
        CALLS.clear()
        self.assertIsNone(self.get("/api/spine/world/changes")["items"][0]["drift_summary"])   # 우리 경로는 생성하지 않는다

    def test_checkpoint_for_topic_without_narrative_is_empty(self):
        self.assertEqual(self.get("/api/spine/world/checkpoint?topic=없는주제")["status"], "empty")


if __name__ == "__main__":
    unittest.main()

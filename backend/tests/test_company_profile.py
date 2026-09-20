"""웹 조사 기업 개요: 출처 검증, 저장·재사용, 조사 레인 상태 (D-188)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import company_profile as cp
from routers.company_profile import router

RAW = {
    "overview": "HPSP는 고압 수소 어닐링 장비를 만드는 반도체 장비 회사다.",
    "business_lines": [{"name": "고압 수소 어닐링 장비", "description": "매출의 대부분", "share_pct": 95.0, "source_ids": [1, 9]}],
    "products_customers": [{"text": "주요 고객은 메모리·파운드리 대기업", "source_ids": [2]}],
    "competitors": ["경쟁사 A"],
    "drivers": [{"text": "HBM·선단 공정 확대", "source_ids": [2]}],
    "risks": [{"text": "고객 집중", "source_ids": [1]}],
    "recent_events": [{"date": "2026-09-07", "title": "반기보고서 제출", "source_ids": [1]}],
    "sources": [
        {"id": 1, "url": "https://dart.fss.or.kr/x", "title": "반기보고서", "publisher": "DART", "published_at": "2026-08-14", "kind": "filing", "excerpt": "사업의 개요…"},
        {"id": 2, "url": "https://news.example.com/a", "title": "기사", "publisher": "뉴스", "published_at": "2026/09/01", "kind": "news", "excerpt": "HBM…"},
        {"id": 3, "url": "javascript:alert(1)", "title": "나쁜 링크", "kind": "other", "excerpt": ""},
        {"id": 4, "url": "https://dart.fss.or.kr/x", "title": "중복", "kind": "filing", "excerpt": ""},
    ],
    "gaps": ["증권사 리포트 원문은 확인하지 못함"],
}
TOOL_RESULTS = [{"name": "WebFetch", "input": {"url": "https://dart.fss.or.kr/x"}, "content": "…"}]


class FinalizeTests(unittest.TestCase):
    def test_sources_are_sanitized_and_citations_pruned(self):
        payload = cp.finalize(RAW, TOOL_RESULTS)
        self.assertEqual([s["id"] for s in payload["sources"]], [1, 2], "non-http and duplicate URLs are dropped")
        self.assertTrue(payload["sources"][0]["fetched"])
        self.assertFalse(payload["sources"][1]["fetched"])
        self.assertIsNone(payload["sources"][1]["published_at"], "non ISO date becomes unknown")
        self.assertEqual(payload["business_lines"][0]["source_ids"], [1], "citation to a missing source id is removed")
        with self.assertRaises(cp.ProfileUnavailable):
            cp.finalize(None)
        with self.assertRaises(cp.ProfileUnavailable):
            cp.finalize({"overview": ""})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "db.sqlite"
        conn = self.connect()
        conn.executescript("""
            CREATE TABLE companies(corp_code TEXT, corp_name TEXT, stock_code TEXT, market TEXT, sector TEXT);
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT, url TEXT,
              published_at TEXT, fetched_at TEXT DEFAULT (datetime('now')), raw_content TEXT, markdown TEXT, content_hash TEXT, UNIQUE(source_type, source_id));
        """ + cp.SCHEMA)
        conn.execute("INSERT INTO companies VALUES ('01288827','HPSP','403870','KOSDAQ','반도체 장비')")
        conn.commit(); conn.close()
        patch.object(cp, "connect", self.connect).start()
        patch.object(cp.llm, "llm_engine", lambda: "claude-code").start()
        self.addCleanup(patch.stopall)

    def connect(self):
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        return conn

    def runner(self, prompt, **kwargs):
        self.prompts.append((prompt, kwargs))
        import json
        return SimpleNamespace(text="설명…\n" + json.dumps(RAW, ensure_ascii=False), tool_results=TOOL_RESULTS, cost_usd=.31, model="sonnet")

    def test_ensure_profile_saves_versions_excerpts_and_reuses_within_24h(self):
        self.prompts = []
        profile, reused = cp.ensure_profile("403870", "HPSP", "반도체 장비", "HBM 관심", runner=self.runner)
        self.assertFalse(reused)
        self.assertEqual((profile["version"], profile["source_count"], profile["cost_usd"]), (1, 2, .31))
        self.assertIn("HPSP", self.prompts[0][0]); self.assertIn("HBM 관심", self.prompts[0][0])
        self.assertEqual(self.prompts[0][1]["tools"], ("WebSearch", "WebFetch"))
        conn = self.connect()
        docs = conn.execute("SELECT source_id, title, published_at, markdown FROM raw_documents WHERE source_type='web' ORDER BY id").fetchall()
        self.assertEqual(len(docs), 2)
        self.assertTrue(docs[0]["source_id"].startswith("403870:"))
        self.assertIn("HPSP · DART · filing", docs[0]["markdown"])
        again, reused = cp.ensure_profile("403870", "HPSP", runner=self.runner)
        self.assertTrue(reused); self.assertEqual(again["version"], 1); self.assertEqual(len(self.prompts), 1)
        forced, reused = cp.ensure_profile("403870", "HPSP", force=True, runner=self.runner)
        self.assertFalse(reused); self.assertEqual(forced["version"], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0], 2, "same URLs are not duplicated")
        conn.close()

    def test_router_returns_profile_and_maps_failures(self):
        self.prompts = []
        app = FastAPI(); app.include_router(router); client = TestClient(app)
        self.assertIsNone(client.get("/api/spine/company-profile/403870").json()["profile"])
        self.assertEqual(client.get("/api/spine/company-profile/000000").status_code, 404)
        with patch.object(cp.llm, "run", self.runner):
            built = client.post("/api/spine/company-profile/403870", json={"reason": "테스트"})
        self.assertEqual(built.status_code, 200, built.text)
        self.assertEqual(built.json()["profile"]["overview"], RAW["overview"])
        with patch.object(cp.llm, "run", lambda *a, **k: SimpleNamespace(text="JSON 아님", tool_results=[], cost_usd=.1, model="sonnet")):
            failed = client.post("/api/spine/company-profile/403870", json={"force": True})
        self.assertEqual(failed.status_code, 502)
        self.assertIn("JSON", failed.json()["detail"])


if __name__ == "__main__":
    unittest.main()

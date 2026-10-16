"""문서 상세 '논점별 관련 자료' (D-233) — 기준 미달 제외·중복 제외·원문 인용·상태 전이."""
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import doc_claims as dc


class ParseAndQuoteTests(unittest.TestCase):
    def test_parse_drops_incomplete_and_caps(self):
        text = json.dumps({"claims": [{"claim": "a", "query_ko": "ㄱ", "query_en": "x"}, {"claim": "b"},
                                      {"claim": "c", "query_ko": "ㄷ"}, {"claim": "d", "query_ko": "ㄹ"},
                                      {"claim": "e", "query_ko": "ㅁ"}]})
        self.assertEqual([c["claim"] for c in dc._parse(text)], ["a", "c", "d"])

    def test_table_rows_are_not_quotes(self):
        self.assertEqual(dc._sentences("New Member Values | Q4 Highlights | Lowering Everyday Low Prices $13.79"), [])
        self.assertEqual(dc._sentences("Digital | Q3 Highlights Top Sales Growth Categories: ● Pharmacy ● Gold"), [])
        self.assertEqual(dc._sentences("By subscribing, you agree to the terms of this newsletter service."), [])

    def test_quote_skips_boilerplate_and_is_verbatim(self):
        text = ("As Senior Analyst, Graphics, Jeff covers everything from integrated graphics processors.\n"
                "Microsoft will deploy AMD Helios racks across its new AI data centers next year.")
        with patch("pipeline.rerank.rerank", side_effect=lambda q, ss: [1.0] * len(ss)):
            q = dc.pick_quote("AMD 랙 도입", text)
        self.assertEqual(q, "Microsoft will deploy AMD Helios racks across its new AI data centers next year.")


class FindRelatedTests(unittest.TestCase):
    def hit(self, i, score):
        return {"id": i, "rerank_score": score, "excerpt": f"[블로그·2026-10-01] 제목\n전력망이 데이터센터 증설 속도의 상한을 정한다는 분석 {i}번이 나왔다."}

    def test_threshold_dedupe_and_hidden_claims(self):
        claims = [{"claim": "A", "query_ko": "a", "query_en": ""}, {"claim": "B", "query_ko": "b", "query_en": ""},
                  {"claim": "C", "query_ko": "c", "query_en": ""}]
        results = {"a": [self.hit(1, 0.5), self.hit(2, 0.1), self.hit(3, 0.0), self.hit(9, 0.9)],
                   "b": [self.hit(2, 0.4), self.hit(4, -1.5)],        # 2는 이미 A에, 4는 기준 미달
                   "c": [self.hit(5, -0.3)]}
        with patch("pipeline.rag.retrieve_docs", side_effect=lambda q, **kw: results[q]), \
             patch.object(dc, "_same_event", return_value={3}), \
             patch("pipeline.rerank.rerank", side_effect=lambda q, ss: [0.0] * len(ss)):
            out = dc.find_related(9, claims)
        self.assertEqual([(c["claim"], [r["id"] for r in c["related"]]) for c in out], [("A", [1, 2]), ("C", [5])])  # 3=같은 실적 발표
        self.assertTrue(out[0]["related"][0]["quote"].startswith("전력망이"))

    def test_repeated_quote_is_skipped(self):
        same = {"rerank_score": 0.5, "excerpt": "[블로그] 제목\n감정가의 4분의 1을 매년 이행강제금으로 계속 물어야 하는 상황이다."}
        with patch("pipeline.rag.retrieve_docs", return_value=[{"id": 1, **same}, {"id": 2, **same}]), \
             patch.object(dc, "_same_event", return_value=set()), \
             patch("pipeline.rerank.rerank", side_effect=lambda q, ss: [0.0] * len(ss)):
            out = dc.find_related(9, [{"claim": "A", "query_ko": "a", "query_en": ""}])
        self.assertEqual([r["id"] for r in out[0]["related"]], [1])

    def test_without_reranker_fails_loudly(self):
        with patch("pipeline.rag.retrieve_docs", return_value=[{"id": 1, "excerpt": "x"}]), \
             patch.object(dc, "_same_event", return_value=set()):
            with self.assertRaises(dc.RerankUnavailable):
                dc.find_related(9, [{"claim": "A", "query_ko": "a", "query_en": ""}])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db")
        c = self.connect()
        c.executescript(dc.SCHEMA + """
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, url TEXT, title TEXT,
                published_at TEXT, markdown TEXT, raw_content TEXT, content_hash TEXT);
            CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT);
            CREATE TABLE blog_sources(url TEXT, blog_name TEXT);
            CREATE TABLE youtube_channels(channel_id TEXT, title TEXT);
            CREATE TABLE scrap_links(doc_id INTEGER, channel TEXT);
            INSERT INTO telegram_channels VALUES ('ch', '채널');""")
        c.execute("INSERT INTO raw_documents VALUES (1,'blog','','','본문 긴 글','2026-10-01',?,NULL,'h1')", ("가" * 800,))
        c.execute("INSERT INTO raw_documents VALUES (2,'telegram','ch/2','','짧은 글','2026-10-02','짧다',NULL,'h2')")
        c.commit()
        c.close()
        self.p = patch.object(dc, "get_connection", side_effect=self.connect)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.f.close()

    def connect(self):
        c = sqlite3.connect(self.f.name)
        c.row_factory = sqlite3.Row
        return c

    def test_flow(self):
        self.assertEqual(dc.state(1)["status"], "none")
        self.assertEqual(dc.queue(2), {"status": "skipped", "token": None})     # 짧은 자료는 논점 없이
        job = dc.queue(1)
        self.assertEqual(job["status"], "running")
        self.assertEqual(dc.queue(1), {"status": "running", "token": None})    # 중복 실행 없음
        with patch.object(dc, "compute", return_value={"claims": [
                {"claim": "논점", "query_ko": "q", "query_en": "", "related": [{"id": 2, "quote": "짧다", "score": 0.3}]}]}):
            dc.execute(1, job["token"])
        s = dc.state(1)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["claims"][0]["related"][0]["channel"], "채널")
        c = self.connect()
        c.execute("UPDATE raw_documents SET content_hash='h1b' WHERE id=1")       # 원문이 바뀌면 다시 만든다
        c.commit()
        self.assertEqual(dc.state(1)["status"], "none")

    def test_failure_is_reported(self):
        job = dc.queue(1)
        with patch.object(dc, "compute", side_effect=dc.RerankUnavailable("리랭커 없음")):
            dc.execute(1, job["token"])
        s = dc.state(1)
        self.assertEqual(s["status"], "failed")
        self.assertIn("리랭커 없음", s["error"])


if __name__ == "__main__":
    unittest.main()

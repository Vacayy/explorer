"""피드 전망 추출 — 대상 고르기(LLM 0)와 환각 방지(인용문 원문 확인)."""
import sqlite3
import unittest

from pipeline.exp_feed import METRICS, candidates, quote_in_doc, schema


def db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE raw_documents (id INTEGER, title TEXT, url TEXT, published_at TEXT, source_type TEXT, markdown TEXT)")
    conn.execute("CREATE TABLE exp_feed_docs (doc_id INTEGER, status TEXT, processed_at TEXT)")
    conn.executemany("INSERT INTO raw_documents VALUES (?,?,?,datetime('now','-1 day'),'telegram',?)", rows)
    return conn


class ExpFeedTests(unittest.TestCase):
    def test_candidate_needs_forecast_org_and_chip_words(self):
        conn = db([(1, "골드만삭스, HBM 가격 전망 상향", "u1", "골드만삭스는 2027년 HBM 가격이 오를 것으로 전망했다"),
                   (2, "HBM 가격 상승", "u2", "HBM 가격이 올랐다"),                       # 기관·전망 없음
                   (3, "골드만삭스, HBM 가격 전망 상향", "u3", "골드만삭스는 HBM 가격 전망을 올렸다"),   # 같은 제목(다른 출처) — 한 번만
                   (4, "모건스탠리 여행 업종 전망", "u4", "모건스탠리는 항공 수요를 전망했다")])      # 밸류체인 낱말 없음
        self.assertEqual([d["id"] for d in candidates(conn)], [1])

    def test_quote_must_exist_in_document(self):
        text = "JP모건은 미국 하이퍼스케일러의\n데이터센터 CAPEX가 2026년 85% 증가할 것으로 봤다."
        self.assertTrue(quote_in_doc("JP모건은 미국 하이퍼스케일러의 데이터센터 CAPEX가 2026년 85% 증가", text))   # 줄바꿈·공백 무시
        self.assertFalse(quote_in_doc("JP모건은 2026년 설비투자가 두 배로 늘 것으로 예상", text))             # 바꿔 쓴 인용은 버린다
        self.assertFalse(quote_in_doc("85%", text))                                                        # 너무 짧은 인용

    def test_schema_has_no_catch_all_metric(self):
        self.assertNotIn("other", METRICS)
        enum = schema()["properties"]["claims"]["items"]["properties"]["node_key"]["enum"]
        self.assertIn("", enum)
        self.assertIn("memory", enum)

    def test_org_names_are_unified(self):
        from pipeline.exp_feed import norm_org
        self.assertEqual(norm_org("Goldman Sachs"), "골드만삭스")
        self.assertEqual(norm_org("J.P. Morgan"), "JP모건")
        self.assertEqual(norm_org("메리츠증권"), "메리츠증권")       # 목록에 없으면 그대로


if __name__ == "__main__":
    unittest.main()

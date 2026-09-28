"""내러티브 엣지 출처(D-204): 모델이 댄 근거 번호·인용을 원문에서 확인한 뒤에만 출처로 붙인다."""
import sqlite3
import unittest

from pipeline.narrative import _persist_causal, doc_labels, verify_edge_evidence


def db():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT, markdown TEXT);
        CREATE TABLE entities(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT, meta_json TEXT);
        CREATE TABLE entity_merges(old_name TEXT, type TEXT, survivor_id INTEGER);
        CREATE TABLE entity_relations(id INTEGER PRIMARY KEY AUTOINCREMENT, src_id INTEGER, dst_id INTEGER, rel_type TEXT,
            epistemic_type TEXT, confidence REAL, effect_strength TEXT, effect_direction TEXT, source_doc_id INTEGER,
            source_status TEXT, source_quote TEXT, mechanism TEXT, reference_period TEXT, time_orientation TEXT,
            narrative_id INTEGER, geo_scope TEXT, valid_from TEXT);
        CREATE TABLE narrative_edge_evidence(id INTEGER PRIMARY KEY, entity_relation_id INTEGER, narrative_id INTEGER,
            doc_id INTEGER, quote TEXT, UNIQUE(entity_relation_id, narrative_id));
        INSERT INTO raw_documents VALUES (1, '애플($AAPL)의 앱스토어 매출이 10년 만에 처음으로 감소했습니다.', ''),
                                         (2, 'Launching Bill Payments in India', 'People can pay household bills on WhatsApp.');
    """)
    return c


EDGE = {"from": "앱스토어 매출 감소", "to": "플랫폼 생태계 락인", "rel": "CAUSES", "confidence": 0.4}


class Verify(unittest.TestCase):
    def setUp(self):
        self.c = db(); self.labels = doc_labels([{"id": 1}, {"id": 2}])

    def test_quote_found_in_cited_doc_ignoring_spacing_and_punctuation(self):
        edge = {**EDGE, "evidence": ["D1"], "quote": "앱스토어 매출이 10년 만에 처음으로 감소"}
        self.assertEqual(verify_edge_evidence(self.c, edge, self.labels)[0], 1)
        spaced = {**edge, "quote": "앱스토어매출이, 10년만에  처음으로 감소"}
        self.assertEqual(verify_edge_evidence(self.c, spaced, self.labels)[0], 1)
        self.assertEqual(verify_edge_evidence(self.c, {**edge, "evidence": "[d1]"}, self.labels)[0], 1)

    def test_wrong_doc_paraphrase_short_or_missing_is_unverified(self):
        wrong_doc = {**EDGE, "evidence": ["D2"], "quote": "앱스토어 매출이 10년 만에 처음으로 감소"}
        paraphrase = {**EDGE, "evidence": ["D1"], "quote": "애플 앱 수익이 줄었다"}
        short = {**EDGE, "evidence": ["D1"], "quote": "애플"}
        unknown = {**EDGE, "evidence": ["D9"], "quote": "앱스토어 매출이 10년 만에"}
        for edge in (wrong_doc, paraphrase, short, unknown, EDGE):
            self.assertEqual(verify_edge_evidence(self.c, edge, self.labels), (None, None), edge)


class Persist(unittest.TestCase):
    def setUp(self):
        self.c = db(); self.labels = doc_labels([{"id": 1}, {"id": 2}])

    def rows(self):
        return [dict(r) for r in self.c.execute("SELECT source_doc_id, source_status, source_quote FROM entity_relations ORDER BY id")]

    def test_narrative_edges_get_only_verified_sources(self):
        causal = {"edges": [{**EDGE, "evidence": ["D1"], "quote": "앱스토어 매출이 10년 만에 처음으로 감소"},
                            {"from": "소비자 AI", "to": "앱스토어 매출 감소", "evidence": ["D2"], "quote": "AI 인터페이스로 이동"}]}
        _persist_causal(self.c, 7, None, causal, labels=self.labels)
        self.assertEqual(self.rows(), [
            {"source_doc_id": 1, "source_status": "verified", "source_quote": "앱스토어 매출이 10년 만에 처음으로 감소"},
            {"source_doc_id": None, "source_status": "unverified", "source_quote": None}])
        ev = [dict(r) for r in self.c.execute("SELECT doc_id, quote FROM narrative_edge_evidence ORDER BY id")]
        self.assertEqual(ev[0]["doc_id"], 1); self.assertIsNone(ev[1]["doc_id"])

    def test_later_verified_evidence_fills_unverified_edge_but_never_overwrites_verified(self):
        _persist_causal(self.c, 7, None, {"edges": [dict(EDGE)]}, labels=self.labels)
        self.assertEqual(self.rows()[0]["source_status"], "unverified")
        good = {"edges": [{**EDGE, "evidence": ["D1"], "quote": "앱스토어 매출이 10년 만에 처음으로 감소"}]}
        _persist_causal(self.c, 8, None, good, labels=self.labels)
        self.assertEqual(self.rows()[0]["source_doc_id"], 1)
        self.c.execute("INSERT INTO raw_documents VALUES (3, '앱스토어 매출이 10년 만에 처음으로 감소 — 재인용', '')")
        _persist_causal(self.c, 9, None, {"edges": [{**EDGE, "evidence": ["D3"], "quote": "재인용"}]}, labels={"D3": 3})
        self.assertEqual(self.rows()[0]["source_doc_id"], 1, "verified source is not replaced")

    def test_document_and_scenario_callers_keep_their_status(self):
        _persist_causal(self.c, None, 2, {"edges": [dict(EDGE)]}, conf_cap=0.5)
        _persist_causal(self.c, None, None, {"edges": [{"from": "가정 사건", "to": "섹터"}]}, source_status="scenario")
        self.assertEqual([(r["source_doc_id"], r["source_status"]) for r in self.rows()], [(2, "document"), (None, "scenario")])


if __name__ == "__main__":
    unittest.main()


class EdgeSourceDetail(unittest.TestCase):
    def setUp(self):
        from pipeline.narrative import edge_source
        self.edge_source = edge_source
        self.c = db()
        self.c.executescript("""
            ALTER TABLE raw_documents ADD COLUMN source_type TEXT; ALTER TABLE raw_documents ADD COLUMN source_id TEXT;
            ALTER TABLE raw_documents ADD COLUMN url TEXT; ALTER TABLE raw_documents ADD COLUMN published_at TEXT;
            ALTER TABLE entity_relations ADD COLUMN legacy_source_doc_id INTEGER;
            CREATE TABLE narratives(id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT);
            CREATE TABLE blog_sources(url TEXT, blog_name TEXT); CREATE TABLE youtube_channels(channel_id TEXT, title TEXT);
            CREATE TABLE scrap_links(doc_id INTEGER, channel TEXT);
            UPDATE raw_documents SET source_type='telegram', source_id='teamctrine/15706' WHERE id=1;
            UPDATE raw_documents SET source_type='blog', source_id='https://about.fb.com/x', url='https://about.fb.com/x' WHERE id=2;
            INSERT INTO telegram_channels VALUES ('teamctrine', '팀 크트린');
        """)

    def test_verified_shows_doc_quote_channel_and_flags_thin_posts(self):
        good = {"edges": [{**EDGE, "evidence": ["D1"], "quote": "앱스토어 매출이 10년 만에 처음으로 감소"}]}
        _persist_causal(self.c, 7, None, good, labels=doc_labels([{"id": 1}, {"id": 2}]))
        d = self.edge_source(self.c, 1)
        self.assertEqual((d["status"], d["doc"]["id"], d["doc"]["channel"], d["doc"]["thin"]), ("verified", 1, "팀 크트린", True))
        self.assertEqual(d["quote"], "앱스토어 매출이 10년 만에 처음으로 감소")
        self.assertEqual(len(d["evidence"]), 1)

    def test_legacy_edge_never_presents_the_recorded_doc_as_its_source(self):
        self.c.execute("INSERT INTO entities(type,name) VALUES ('event','앱스토어 매출 감소'),('sector','인터넷 플랫폼 섹터')")
        self.c.execute("INSERT INTO entity_relations(src_id,dst_id,rel_type,source_doc_id) VALUES (1,2,'CAUSES',2)")
        d = self.edge_source(self.c, 1)
        self.assertEqual((d["status"], d["doc"], d["recorded_doc_id"]), ("legacy_unverified", None, 2))
        self.assertIsNone(self.edge_source(self.c, 99))

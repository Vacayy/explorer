"""수집 적재 계약: 외부 수집·모델 없이 임시 SQLite에서 검증한다."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.base import RawDoc
from pipeline import store


class StoreIngestContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.sqlite"
        with closing(self.connect()) as conn:
            conn.executescript("""
                CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT,
                  title TEXT, url TEXT, published_at TEXT, raw_content TEXT, markdown TEXT,
                  content_hash TEXT, media_json TEXT, digest_status TEXT, fetched_at TEXT,
                  UNIQUE(source_type, source_id));
                CREATE TABLE enrichments (doc_id INTEGER, summary TEXT, sentiment TEXT,
                  time_orientation TEXT, reference_period TEXT, model TEXT, content_hash TEXT);
                CREATE TABLE entities (id INTEGER PRIMARY KEY, type TEXT, name TEXT);
                CREATE TABLE entity_links (doc_id INTEGER, entity_id INTEGER, link_type TEXT,
                  confidence REAL, UNIQUE(doc_id, entity_id, link_type));
                CREATE TABLE entity_keywords (entity_id INTEGER, keyword TEXT, status TEXT);
                CREATE TABLE entity_relations (src_id INTEGER, dst_id INTEGER, rel_type TEXT,
                  epistemic_type TEXT, confidence REAL, source_doc_id INTEGER);
            """)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_new_unchanged_changed_and_keyword_upgrade(self):
        doc = RawDoc(source_type="fixture", source_id="1", title="fixture", raw_content="one")
        result = {"summary": "initial", "model": "keyword", "industries": [], "topics": []}
        with patch.object(store, "get_connection", side_effect=self.connect), \
             patch.object(store.enrich_mod, "llm_available", return_value=False) as available, \
             patch.object(store.enrich_mod, "enrich", return_value=result) as enrich:
            first = store.store_document(doc)
            self.assertEqual(first["status"], "new")
            self.assertEqual(store.store_document(doc)["status"], "unchanged")
            self.assertEqual(enrich.call_count, 1)
            available.return_value = True
            enrich.return_value = {**result, "summary": "upgraded", "model": "fixture-llm"}
            self.assertEqual(store.store_document(doc)["status"], "unchanged")
            self.assertEqual(enrich.call_count, 2)
            self.assertEqual(store.store_document(doc)["status"], "unchanged")
            self.assertEqual(enrich.call_count, 2)
            doc.raw_content = "two"
            enrich.return_value = {**result, "summary": "changed", "model": "fixture-llm"}
            self.assertEqual(store.store_document(doc), {"doc_id": first["doc_id"], "status": "updated"})
            self.assertEqual(enrich.call_count, 3)
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT summary, model, content_hash FROM enrichments").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["summary"], rows[0]["model"]), ("changed", "fixture-llm"))
            self.assertEqual(rows[0]["content_hash"], store._hash("two"))


if __name__ == "__main__":
    unittest.main()

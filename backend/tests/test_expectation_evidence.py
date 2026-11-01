"""Stored-document inspection used by chat attachments. Run: cd backend && ../.venv/bin/python -m unittest tests/test_expectation_evidence.py."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import expectation_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "corpus.db"
        conn = sqlite3.connect(self.path)
        conn.execute("""CREATE TABLE raw_documents (
            id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT,
            url TEXT, published_at TEXT, fetched_at TEXT, raw_content TEXT,
            markdown TEXT, digest_status TEXT)""")
        fixtures = [
            (1, "telegram", "안녕하세요. 관찰자입니다. HBM 전망", None),
            (2, "youtube", "HBM 정리\n원본 자막 3,000자 → opus 정리본", "ok"),
            (3, "youtube", "안녕하세요. 관찰자입니다. DRAM 전망", "failed"),
            (4, "blog", "(증권사 연구원) NAND 리포트 인용", None),
            (5, "note", "HBM private note", None),
            (6, "telegram", "", None),
        ]
        for i, kind, body, status in fixtures:
            conn.execute("INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (i, kind, f"channel/{i}", "HBM" if i == 6 else "문서", None,
                          None, "2026-09-09", body, body, status))
        conn.commit()
        conn.close()
        self.original = self.path.read_bytes()
        self.patch = patch.object(evidence, "DB_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def get(self, doc_id):
        return evidence.get_document(doc_id).model_dump()

    def test_derived_cannot_be_direct_speaker_evidence(self):
        doc = self.get(2)
        self.assertEqual(doc["text_kind"], "derived_summary")
        self.assertFalse(doc["source_text_available"])
        self.assertEqual(doc["attribution_cues"], [])
        self.assertIsNone(doc["speaker"])

    def test_failed_digest_is_not_failed_transcript(self):
        doc = self.get(3)
        self.assertEqual(doc["text_kind"], "stored_transcript")
        self.assertTrue(doc["source_text_available"])
        self.assertEqual(doc["speaker_status"], "unresolved")
        for cue in doc["attribution_cues"]:
            self.assertEqual(doc["text"][cue["start"]:cue["end"]], cue["text"])
        self.assertEqual(hashlib.sha256(doc["text"].encode()).hexdigest(), doc["text_sha256"])

    def test_reported_speech_is_not_blogger_identity(self):
        doc = self.get(4)
        self.assertIsNone(doc["speaker"])
        self.assertTrue(any(x["kind"] == "reported_speech" for x in doc["attribution_cues"]))

    def test_empty_and_private_and_missing(self):
        self.assertEqual(self.get(6)["text_kind"], "empty")
        self.assertIsNone(evidence.get_document(5))
        self.assertIsNone(evidence.get_document(999))

    def test_read_only_enforced_and_gets_leave_db_unchanged(self):
        with evidence.evidence_connection() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM raw_documents")
        self.get(2)
        self.assertEqual(self.original, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()

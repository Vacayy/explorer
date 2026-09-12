"""Run: cd backend && ../.venv/bin/python -m unittest discover -s tests -p 'test_expectation_evidence.py'."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import expectation_evidence as evidence
from routers.experiment_expectations import router


class EvidenceApiTests(unittest.TestCase):
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
        app = FastAPI()  # no production startup, schema migrations or Telegram bot
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.tmp.cleanup()

    def get(self, suffix="", **kwargs):
        return self.client.get("/api/experiments/expectations/documents" + suffix, **kwargs)

    def test_derived_cannot_be_direct_speaker_evidence(self):
        doc = self.get("/2").json()
        self.assertEqual(doc["text_kind"], "derived_summary")
        self.assertFalse(doc["source_text_available"])
        self.assertEqual(doc["attribution_cues"], [])
        self.assertIsNone(doc["speaker"])

    def test_failed_digest_is_not_failed_transcript(self):
        doc = self.get("/3").json()
        self.assertEqual(doc["text_kind"], "stored_transcript")
        self.assertTrue(doc["source_text_available"])
        self.assertEqual(doc["speaker_status"], "unresolved")
        for cue in doc["attribution_cues"]:
            self.assertEqual(doc["text"][cue["start"]:cue["end"]], cue["text"])
        self.assertEqual(hashlib.sha256(doc["text"].encode()).hexdigest(), doc["text_sha256"])

    def test_reported_speech_is_not_blogger_identity(self):
        doc = self.get("/4").json()
        self.assertIsNone(doc["speaker"])
        self.assertTrue(any(x["kind"] == "reported_speech" for x in doc["attribution_cues"]))

    def test_empty_and_private_and_missing(self):
        self.assertEqual(self.get("/6").json()["text_kind"], "empty")
        self.assertEqual(self.get("/5").status_code, 404)
        self.assertEqual(self.get("/999").status_code, 404)

    def test_pagination_does_not_duplicate_or_skip(self):
        ids, cursor = [], None
        for _ in range(10):
            params = {"limit": 1}
            if cursor:
                params["before_id"] = cursor
            page = self.get(params=params).json()
            ids.extend(d["id"] for d in page["items"])
            if not page["has_more"]:
                break
            cursor = page["next_before_id"]
        self.assertEqual(ids, [6, 4, 3, 2, 1])

    def test_scan_limit_can_return_empty_with_cursor(self):
        conn = sqlite3.connect(self.path)
        for i in range(10, 515):
            conn.execute("INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (i, "blog", str(i), "unrelated", None, None, None, "none", "none", None))
        conn.commit()
        conn.close()
        page = self.get().json()
        self.assertEqual(page["items"], [])
        self.assertEqual(page["scanned"], 500)
        self.assertTrue(page["has_more"])
        next_page = self.get(params={"before_id":page["next_before_id"]}).json()
        self.assertEqual([d["id"] for d in next_page["items"]], [6, 4, 3, 2, 1])

    def test_validation_filter_and_unavailable(self):
        self.assertEqual(self.get(params={"product":"unknown"}).status_code, 422)
        self.assertEqual(self.get(params={"limit":51}).status_code, 422)
        self.assertEqual([d["id"] for d in self.get(params={"product":"nand"}).json()["items"]], [4])
        with patch.object(evidence, "DB_PATH", self.path.parent / "absent.db"):
            self.assertEqual(self.get().status_code, 503)
            self.assertFalse((self.path.parent / "absent.db").exists())

    def test_read_only_enforced_and_gets_leave_db_unchanged(self):
        with evidence.evidence_connection() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM raw_documents")
        self.get()
        self.get("/2")
        self.assertEqual(self.original, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()

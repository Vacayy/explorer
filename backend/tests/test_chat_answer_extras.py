"""AI 대화 시안 정렬(ia-redesign §4.14, 개편 4j) — 출처 날짜와 답변 저장.

- 대화 상세는 수집 자료 인용에 게시일(`published_at`)을 붙여 내보낸다. 저장된 인용 JSON은 바꾸지 않는다.
- 저장됨은 대화 답변(`kind='chat'`, ref = 메시지 id)을 받는다.
"""
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routers.spine_conversations import _with_published_at


def _memory_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, published_at TEXT);
        INSERT INTO raw_documents VALUES (16705, '2026-09-06T23:30:07+00:00');
        CREATE TABLE saved_items (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL, url TEXT NOT NULL,
          title TEXT, subtitle TEXT, note TEXT, created_at TEXT DEFAULT (datetime('now')), UNIQUE(kind, ref));
    """)
    return conn


class _NoClose:
    """라우터가 conn.close()를 불러도 테스트 DB가 살아 있게 한다."""
    def __init__(self, conn): self.conn = conn
    def __getattr__(self, name): return getattr(self.conn, name)
    def close(self): pass


class CitationDateTests(unittest.TestCase):
    def test_document_citations_get_published_at(self):
        conn = _memory_db()
        cites = [{"n": 1, "kind": "quote", "title": "시세", "doc_id": None},
                 {"n": 7, "kind": "doc", "title": "자료", "doc_id": 16705},
                 {"n": 8, "kind": "doc", "title": "지워진 자료", "doc_id": 99}]
        out = _with_published_at(conn, cites)
        self.assertEqual([c["published_at"] for c in out], [None, "2026-09-06T23:30:07+00:00", None])
        self.assertNotIn("published_at", cites[1], "stored citations are not mutated")

    def test_non_list_passes_through(self):
        self.assertIsNone(_with_published_at(_memory_db(), None))


class SavedChatTests(unittest.TestCase):
    def test_chat_answer_can_be_saved_and_unknown_kind_is_rejected(self):
        conn = _NoClose(_memory_db())
        with patch("routers.spine_saved.get_connection", return_value=conn):
            client = TestClient(app)
            r = client.post("/api/spine/saved", json={"kind": "chat", "ref": "501", "url": "/chat?id=75", "title": "리서치"})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.json()["kind"], "chat")
            self.assertEqual(client.post("/api/spine/saved", json={"kind": "bogus", "ref": "1", "url": "/"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

"""문서에서 드래그한 인용 — 'AI에게 묻기' (docs/specs/canvas.md §2).

답변 인용(D-146)은 '직전 답변'에서 왔다고 말한다. 문서 인용은 message_id가 없고 doc_id·제목이 있다 —
프롬프트가 출처를 문서로 밝혀야 '직전 답변'으로 오해하지 않는다.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from pipeline import chat

DOC_QUOTE = {"selected": "HBM 출하가 3분기에 두 배", "block": "HBM 출하가 3분기에 두 배로 늘었다. 가격은 유지.",
             "doc_id": 4321, "doc_title": "메모리 업황 점검"}


class DocQuoteTests(unittest.TestCase):
    def turn(self, quote):
        return chat.Turn(question="이게 맞아?", conversation_id=None, ctx={"recent": [], "state": {}}, quote=quote)

    def test_doc_quote_names_the_document_not_the_previous_answer(self):
        text = chat._quote_block(self.turn(DOC_QUOTE))
        self.assertIn("문서", text)
        self.assertIn("메모리 업황 점검", text)
        self.assertIn("doc_id 4321", text)
        self.assertNotIn("직전 답변", text)
        self.assertIn("HBM 출하가 3분기에 두 배로 늘었다", text)   # 문단 맥락

    def test_pasted_study_material_without_doc_id_is_still_a_document(self):
        text = chat._quote_block(self.turn({"selected": "마진 개선", "doc_title": "붙여넣은 메모"}))
        self.assertIn("붙여넣은 메모", text)
        self.assertNotIn("직전 답변", text)
        self.assertNotIn("open_doc", text)

    def test_answer_quote_still_says_previous_answer(self):
        text = chat._quote_block(self.turn({"message_id": 9, "selected": "급증했다"}))
        self.assertIn("직전 답변", text)

    def test_ask_accepts_doc_quote(self):
        with patch("pipeline.conversations.log_question", return_value=7), \
             patch("routers.spine_ask._generate_answer") as gen:
            r = TestClient(app).post("/api/spine/ask", json={"question": "이게 맞아?", "quote": DOC_QUOTE})
        self.assertEqual(r.status_code, 200)
        q = gen.call_args.args[2]
        self.assertEqual(q["doc_id"], 4321)
        self.assertEqual(q["doc_title"], "메모리 업황 점검")
        self.assertIsNone(q["message_id"])


if __name__ == "__main__":
    unittest.main()

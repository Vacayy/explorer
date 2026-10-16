"""AI 대화 패널은 보고 있는 화면을 page_context로 넘긴다 (docs/specs/app-shell.md §5).

'이 종목', '이 문서' 같은 지시어를 라우터·종합이 화면 기준으로 해석하게 하고, 메시지 본문에는 저장하지 않는다.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from pipeline import chat

PAGE = {"kind": "stock", "label": "종목 SK하이닉스(000660) · 개요", "path": "/analyze/000660/summary", "ref": "000660"}


class PageContextTests(unittest.TestCase):
    def turn(self, page_context=None):
        return chat.Turn(question="이 종목 왜 빠졌어?", conversation_id=None, ctx={"recent": [], "state": {}}, page_context=page_context)

    def test_router_prompt_names_the_page(self):
        with patch("pipeline.chat_memory.context_block", return_value=""):
            text = chat._router_user(self.turn(PAGE))
        self.assertIn("[사용자가 지금 보고 있는 화면]", text)
        self.assertIn("SK하이닉스(000660)", text)
        self.assertIn("/analyze/000660/summary", text)

    def test_without_page_context_nothing_is_added(self):
        with patch("pipeline.chat_memory.context_block", return_value=""):
            self.assertNotIn("보고 있는 화면", chat._router_user(self.turn()))

    def test_ask_passes_page_context_but_stores_only_the_question(self):
        with patch("pipeline.conversations.log_question", return_value=7) as log, \
             patch("routers.spine_ask._generate_answer") as gen:
            r = TestClient(app).post("/api/spine/ask", json={"question": "이 종목 왜 빠졌어?", "page_context": PAGE})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(log.call_args.args[0], "이 종목 왜 빠졌어?")
        self.assertEqual(gen.call_args.kwargs["page_context"]["ref"], "000660")


if __name__ == "__main__":
    unittest.main()

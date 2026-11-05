"""AI 대화 › 대상 붙이기 (ia-redesign §4.14a, D-311).

- 후보 검색: 종류별 묶음, '전체'는 종류마다 4개, 종류를 고르면 더 많이. 빈 검색어는 최근 서사·질문·자료·리포트·Peer 그룹.
- POST /ask `attachments`: 대화 state_json.attached_refs에 저장(같은 대상 한 번, 새 대상 5개까지), 질문 메시지에도 남김.
  자료(doc) 대상은 기존 첨부(attached_doc_ids)와 같은 목록. 없는 대상은 422.
- 대화 상세: 메시지별 attachments, 대화의 attached_refs(사라진 대상은 available=false).
- 답변: 라우터·종합 입력에 '[대화에 붙인 대상]' 블록, 식별자로 근거 수집. LLM 호출 수는 그대로(모의).
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from pipeline import chat, chat_targets as ct
from routers.peers import DATA, read_runtime


class ChatTargetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        patch.object(ct, "_peer_runtime", lambda: read_runtime(root=Path(self.tmp.name) / "none", data=DATA)).start()
        self.addCleanup(patch.stopall)
        database.init_db()
        conn = database.get_connection()
        conn.executemany("INSERT INTO companies (corp_code, corp_name, stock_code, market, sector) VALUES (?,?,?,?,?)", [
            ("c1", "SK하이닉스", "000660", "KOSPI", "반도체"), ("c2", "SK하이닉스우", "000665", "KOSPI", "반도체")])
        for day, close in (("2026-11-03", 200000), ("2026-11-04", 204200)):
            conn.execute("INSERT INTO stock_prices (stock_code, trade_date, close, market_cap) VALUES ('000660', ?, ?, 1e14)", (day, close))
        for i, (topic, title, sup) in enumerate([("HBM", "HBM 공급 우위", None), ("HBM", "옛 버전", "2026-11-01"), ("추론 전환", "메모리 재평가", None),
                                                 ("지정학", "보관된 서사", "2026-10-01")], 1):
            conn.execute("INSERT INTO narratives (topic, version, title, body, created_at, superseded_at) VALUES (?,?,?,?,?,?)",
                         (topic, i, title, f"{title} 본문", f"2026-11-0{i}", sup))
        conn.execute("INSERT INTO questions (id, text, status, lead_verdict, updated_at) VALUES (7, '오픈소스 모델 확장이 한국 메모리에 주는 영향', 'tracking', 'mixed', '2026-11-04')")
        conn.execute("INSERT INTO sub_questions (question_id, text, verdict) VALUES (7, '토큰 가격 하락이 메모리 수요를 줄이나', 'unknown')")
        for i in range(1, 8):
            conn.execute("INSERT INTO raw_documents (id, source_type, source_id, title, published_at, markdown) VALUES (?, 'telegram', ?, ?, ?, '본문')",
                         (100 + i, f"s{i}", f"하이닉스 HBM 코멘트 {i}", f"2026-11-0{i % 5 + 1}T00:00:00"))
        conn.execute("INSERT INTO entities (id, type, name, status) VALUES (501, 'person', '젠슨 황', 'active'), (502, 'theme', 'HBM', 'active'), (503, 'sector', '반도체', 'active')")
        conn.execute("INSERT INTO reports (anchor_topic, title, body, created_at) VALUES ('반도체', 'HBM 병목', '리포트 본문', '2026-07-27')")
        conn.execute("INSERT INTO transcript_follow (ticker, company_name, group_label, active) VALUES ('MU', 'Micron Technology', '반도체', 1)")
        conn.commit()
        conn.close()
        self.client = TestClient(app)

    def state(self, cid):
        conn = database.get_connection()
        try:
            return json.loads(conn.execute("SELECT state_json FROM conversations WHERE id=?", (cid,)).fetchone()[0] or "{}")
        finally:
            conn.close()

    def ask(self, **body):
        with patch("routers.spine_ask._generate_answer") as gen:
            r = self.client.post("/api/spine/ask", json={"question": "4분기 HBM 가격 협상 정리해줘", **body})
        return r, gen

    # ── 후보 검색 ──
    def test_search_groups_by_kind_with_four_each(self):
        body = self.client.get("/api/spine/chat/targets", params={"q": "하이"}).json()
        kinds = [g["kind"] for g in body["groups"]]
        self.assertEqual(kinds[:2], ["stock", "doc"])
        stock = body["groups"][0]["items"]
        self.assertEqual([s["label"] for s in stock], ["SK하이닉스", "SK하이닉스우"])
        self.assertEqual((stock[0]["code"], round(stock[0]["change_pct"], 1)), ("000660", 2.1))
        docs = next(g for g in body["groups"] if g["kind"] == "doc")["items"]
        self.assertEqual(len(docs), 4, "all view shows four per kind")
        self.assertEqual(docs[0]["date"], "2026-11-05", "documents are recent first")

    def test_kind_filter_returns_more_and_each_kind_is_searchable(self):
        docs = self.client.get("/api/spine/chat/targets", params={"q": "하이", "kind": "doc"}).json()
        self.assertEqual(len(docs["groups"][0]["items"]), 7)
        cases = {"narrative": ("HBM", "HBM"), "question": ("오픈소스", "오픈소스 모델 확장이 한국 메모리에 주는 영향"), "person": ("젠슨", "젠슨 황"),
                 "theme": ("반도", "반도체"), "report": ("반도체", "반도체"), "us_stock": ("MU", "Micron Technology"), "peer_group": ("반도체", "반도체 밸류체인")}
        for kind, (q, label) in cases.items():
            items = self.client.get("/api/spine/chat/targets", params={"q": q, "kind": kind}).json()["groups"][0]["items"]
            self.assertIn(label, [i["label"] for i in items], kind)
        narratives = self.client.get("/api/spine/chat/targets", params={"q": "", "kind": "narrative"}).json()["groups"][0]["items"]
        self.assertEqual([n["label"] for n in narratives], ["추론 전환", "HBM"], "current versions only, archived topics excluded")
        self.assertEqual(self.client.get("/api/spine/chat/targets", params={"q": "#7", "kind": "question"}).json()["groups"][0]["items"][0]["code"], "#7")
        self.assertEqual(self.client.get("/api/spine/chat/targets", params={"kind": "nope"}).status_code, 422)

    # ── 요청 · 저장 ──
    def test_attachments_persist_dedupe_and_map_docs(self):
        refs = [{"kind": "stock", "ref": "000660", "label": "SK하이닉스"}, {"kind": "stock", "ref": "000660", "label": "SK하이닉스"},
                {"kind": "narrative", "ref": "HBM", "label": "HBM"}, {"kind": "doc", "ref": "101", "label": "코멘트"}]
        r, gen = self.ask(attachments=refs)
        self.assertEqual(r.status_code, 200, r.text)
        cid = r.json()["conversation_id"]
        st = self.state(cid)
        self.assertEqual([(a["kind"], a["ref"]) for a in st["attached_refs"]], [("stock", "000660"), ("narrative", "HBM"), ("doc", "101")])
        self.assertEqual(st["attached_doc_ids"], [101], "doc targets are the existing attached-document path")
        detail = self.client.get(f"/api/spine/conversations/{cid}").json()
        self.assertEqual([a["ref"] for a in detail["messages"][0]["attachments"]], ["000660", "HBM", "101"])
        self.assertEqual(detail["attached_refs"][0]["change_pct"] is not None, True)

        # 다음 질문: attachments 없이 보내면 그대로 남는다
        with patch("routers.spine_ask._generate_answer"):
            self.client.post("/api/spine/ask", json={"question": "이어서", "conversation_id": cid})
        self.assertEqual(len(self.state(cid)["attached_refs"]), 3)
        # ×로 뺀 뒤 보내면 전체 목록으로 바뀐다
        with patch("routers.spine_ask._generate_answer"):
            self.client.post("/api/spine/ask", json={"question": "뺐다", "conversation_id": cid, "attachments": refs[2:3]})
        st = self.state(cid)
        self.assertEqual([a["ref"] for a in st["attached_refs"]], ["HBM"])
        self.assertEqual(st["attached_doc_ids"], [])

    def test_more_than_five_new_targets_or_missing_target_is_rejected(self):
        many = [{"kind": "doc", "ref": str(100 + i), "label": f"d{i}"} for i in range(1, 7)]
        r, gen = self.ask(attachments=many)
        self.assertEqual(r.status_code, 422)
        self.assertIn("5개", r.json()["detail"])
        gen.assert_not_called()
        r, _ = self.ask(attachments=[{"kind": "narrative", "ref": "지정학", "label": "지정학"}])
        self.assertEqual(r.status_code, 422, "archived narrative cannot be attached")
        r, _ = self.ask(attachments=[{"kind": "planet", "ref": "x", "label": "x"}])
        self.assertEqual(r.status_code, 422)
        # 이미 붙은 대상은 '새 대상' 수에 들지 않는다
        r, _ = self.ask(attachments=many[:5])
        cid = r.json()["conversation_id"]
        with patch("routers.spine_ask._generate_answer"):
            r2 = self.client.post("/api/spine/ask", json={"question": "하나 더", "conversation_id": cid, "attachments": many[:6]})
        self.assertEqual(r2.status_code, 200)

    def test_legacy_document_ids_become_doc_chips(self):
        with patch("pipeline.expectation_evidence.get_document", return_value=object()):
            r, _ = self.ask(document_ids=[101, 102])
        cid = r.json()["conversation_id"]
        detail = self.client.get(f"/api/spine/conversations/{cid}").json()
        self.assertEqual([(a["kind"], a["ref"], a["label"]) for a in detail["attached_refs"]],
                         [("doc", "101", "하이닉스 HBM 코멘트 1"), ("doc", "102", "하이닉스 HBM 코멘트 2")])

    def test_vanished_target_is_marked_unavailable(self):
        r, _ = self.ask(attachments=[{"kind": "narrative", "ref": "추론 전환", "label": "추론 전환"}])
        cid = r.json()["conversation_id"]
        conn = database.get_connection()
        conn.execute("UPDATE narratives SET superseded_at = '2026-11-05' WHERE topic = '추론 전환'")
        conn.commit(); conn.close()
        ref = self.client.get(f"/api/spine/conversations/{cid}").json()["attached_refs"][0]
        self.assertEqual((ref["label"], ref["available"]), ("추론 전환", False))

    # ── 답변 ──
    def test_prompt_block_lists_kind_label_and_identifier(self):
        turn = chat.Turn(question="이거 영향 있어?", conversation_id=None, ctx={"recent": [], "state": {"attached_refs": [
            {"kind": "stock", "ref": "000660", "label": "SK하이닉스"}, {"kind": "question", "ref": "7", "label": "오픈소스 영향"}]}})
        with patch("pipeline.chat_memory.context_block", return_value=""):
            router_text, synth_text = chat._router_user(turn), chat._synth_user(turn)
        for text in (router_text, synth_text):
            self.assertIn("[대화에 붙인 대상]", text)
            self.assertIn("국내 종목 · SK하이닉스 · 종목코드=000660", text)
            self.assertIn("질문 · 오픈소스 영향 · 질문 번호=7", text)
        plain = chat.Turn(question="q", conversation_id=None, ctx={"recent": [], "state": {}})
        with patch("pipeline.chat_memory.context_block", return_value=""):
            self.assertNotIn("붙인 대상", chat._router_user(plain))

    def test_run_turn_gathers_by_identifier_without_extra_llm_calls(self):
        state = {"attached_refs": [{"kind": "stock", "ref": "000660", "label": "SK하이닉스"}, {"kind": "question", "ref": "7", "label": "q7"},
                                   {"kind": "peer_group", "ref": "foundry", "label": "파운드리"}, {"kind": "report", "ref": "반도체", "label": "반도체"},
                                   {"kind": "narrative", "ref": "HBM", "label": "HBM"}]}
        calls = []

        def fake_llm(prompt, **kw):
            calls.append(kw.get("job"))
            if kw.get("job") == "chat.route":
                return SimpleNamespace(text='{"intent":"lookup","tools":[],"entities":[],"answer_style":"brief"}', label="m", usage={})
            return SimpleNamespace(text="답 [1]", label="m", usage={})

        quote = SimpleNamespace(items=[{"kind": "quote", "title": "실시간 시세", "text": "204,200원", "date": "2026-11-05", "doc_id": None, "href": None}])
        with patch.object(chat.llm, "run", side_effect=fake_llm), \
             patch("pipeline.chat_targets._tool_items", side_effect=lambda call: quote.items if call["name"] == "get_quote" else []):
            turn = chat.run_turn("정리해줘", ctx={"recent": [], "state": state, "note": None, "related": []})
        self.assertEqual(calls, ["chat.route", "chat.answer"], "no extra LLM calls")
        tools = {e["kind"] for e in turn.evidence if e.get("tool") == "attached_targets"}
        self.assertTrue({"quote", "question", "peer_group", "report"} <= tools, tools)
        log = next(t for t in turn.tool_log if t["name"] == "attached_targets")
        self.assertIn("stock=000660", log["args"]["refs"])
        self.assertIn("서사 HBM", log["note"], "empty targets are named")


if __name__ == "__main__":
    unittest.main()

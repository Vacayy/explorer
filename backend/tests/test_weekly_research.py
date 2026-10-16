import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.weekly_reader import ComparisonRequest, ReaderBrief
from models.weekly_research import ReadRequest, ResearchMemo, ResearchStep, SearchRequest
from pipeline.weekly.evidence import Evidence, make_item
from pipeline.weekly.reader_experiment import model_packet, run
from pipeline.weekly.research import ResearchDesk
from pipeline.weekly.store import atomic_write, digest, dumps


class ResearchTest(unittest.TestCase):
    def test_writer_keeps_daily_prices_and_metrics_without_duplicating_them(self):
        packet = copy.deepcopy(self.packet)
        metrics = [{"id": "m1", "value": 4.97, "unit": "%"}]
        points = [{"date": "2026-09-11", "value": 4.97}]
        packet["metrics"] = {"m1": metrics[0]}
        packet["sources"]["s1"] = {"kind": "series", "text": dumps({"calculation": metrics, "week_points": points})}
        before = digest(packet)
        context = model_packet(packet)
        self.assertEqual(context["metrics"], packet["metrics"])
        self.assertEqual(json.loads(context["sources"]["s1"]["text"]), {"week_points": points})
        self.assertEqual(digest(packet), before)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.request = ComparisonRequest(request_key="research-test", source_run_id="a" * 32, workflow="research",
                                         week_start="2026-09-07", week_end="2026-09-11",
                                         outlook_start="2026-09-14", outlook_end="2026-09-18")
        self.packet = {"workflow": "research", "period": {k: str(getattr(self.request, k)) for k in
                      ("week_start", "week_end", "outlook_start", "outlook_end")}, "cutoff": "2026-09-15T00:00:00Z",
                       "sources": {}, "metrics": {}, "charts": {}, "gaps": [], "coverage": {}}
        self.texts = {"d1": "금리 상승이 이번 주 투자 기대를 바꿨다는 저자의 의견이다.",
                      "d2": "기업 수요가 늘었으나 실제 현금흐름은 여전히 약하다.",
                      "d3": "반대 증거로 공급 정상화와 수요 감소 가능성이 제시됐다.",
                      "d4": "미래 발표로서 이전 주 판단에 사용할 수 없는 자료다.",
                      "d5": "참조 Weekly 본문이므로 생성 입력에 사용할 수 없다."}
        conn = sqlite3.connect(self.directory / "corpus.sqlite")
        conn.execute("CREATE TABLE items(id TEXT PRIMARY KEY,kind TEXT,meta TEXT,data TEXT,text TEXT,sha256 TEXT)")
        conn.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,title,text)")
        for sid, text in self.texts.items():
            meta = {"title": sid, "published_at": "2026-09-10T00:00:00Z", "available_at_bound": "2026-09-10T00:00:00Z",
                    "temporal_status": "captured_live", "source_type": "telegram", "source_id": f"channel{sid}/{sid}",
                    "content_kind": "stored_source", "duplicate_group": sid, "url": "https://example.org/" + sid}
            if sid == "d4":
                meta["available_at_bound"] = "2026-09-16T00:00:00Z"
            if sid == "d5":
                meta["url"] = "https://notion.so/3da9e403cb628080a1fed604f8542436"
            Evidence._insert(conn, make_item(sid, "document", meta, {}, text))
        conn.commit()
        conn.close()
        routing = {"captured_at": "2026-09-16T00:00:00Z", "profiles": [{"kind": "telegram", "key": "channeld2", "digest": "매크로 금리",
                   "insights": "매크로", "created_at": "2026-09-16"}], "people": [{"id": 1, "name": "태그인물", "aliases": "Tagged"}], "links": [[2, 1]]}
        atomic_write(self.directory / "routing.json", dumps(routing))
        atomic_write(self.directory / "external-catalog.json", "{}")
        atomic_write(self.directory / "packet.json", dumps(self.packet))
        self.manifest = {"request": self.request.model_dump(mode="json"), "packet_sha256": digest(self.packet), "status": "prepared",
                         "research_inputs": {name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
                                             for name in ("corpus.sqlite", "routing.json", "external-catalog.json")}}
        atomic_write(self.directory / "manifest.json", dumps(self.manifest))
        self.calls = []
        self.material = []

    def question(self, qid):
        return {"id": qid, "question": "기대와 실제 반응의 차이는?", "why_now": "변화", "competing_explanations": ["공급", "수요"],
                "decision_at_stake": "선별 보유", "evidence_needed": ["사건 전후 원문"], "search_terms": ["금리", "수요"], "completion_condition": "반대 증거 검토"}

    def memo(self, qid, sid):
        cite = {"source_id": f"{sid}-r0-{len(self.texts[sid])}", "quote": self.texts[sid]}
        return {"question_id": qid, "answer": "반대 근거를 감안해 선별 보유", "expectations_event_reaction": "예상과 반응을 구분",
                "claims": [{"id": f"{qid}-c{i}", "statement": "출처의 조건부 의견", "kind": "source_view", "citations": [cite], "limitation": "원 저자의 의견"} for i in (1, 2)],
                "strongest_alternative": "수요 둔화", "pricing_interpretation": "반영 완료는 미확인", "response_implication": "추격 보류",
                "change_condition": "실제 현금 개선", "unresolved": []}

    def model(self, payload, timeout, cancelled):
        stage = payload["job"].removeprefix("weekly-reader-")
        self.calls.append((stage, payload))
        if stage == "research-agenda":
            out = {"market_puzzle": "가격과 기대 차이", "questions": [self.question("q1"), self.question("q2")], "deferred": []}
        elif stage in {"research-challenge", "research-postwrite-challenge"}:
            out = {"assessment": "반대 증거 원문 필요", "requests": [{"question_id": "q2" if "postwrite" in stage else "q1", "problem": "공급 정상화 누락", "route": "source", "query": "반대 증거",
                   "evidence_needed": "정상화 원문", "completion_condition": "원문 검토", "decision_impact": "강도 축소"}]}
        elif stage in {"research-decision", "research-revised-decision"}:
            memos = json.loads(payload["prompt"])["memos"]
            latest = {qid: max(m["research_sequence"] for m in memos.values() if m["question_id"] == qid) for qid in ("q1", "q2")}
            adopted = [m for m in memos.values() if m["research_sequence"] == latest[m["question_id"]]]
            out = {"judgment": {k: "반대 근거를 감안해 신규 진입을 보류한다" for k in
                   ("week_in_review", "market_state", "central_question", "preferred_explanation", "strongest_counterargument", "current_response", "opportunity_cost")},
                   "dispositions": [{"claim_id": c["id"], "status": "adopted" if m in adopted else "rejected", "reason": "원문 확인"} for m in memos.values() for c in m["claims"]],
                   "writing_source_ids": sorted({c["source_id"] for memo in adopted for claim in memo["claims"] for c in claim["citations"]}), "unresolved_material": self.material}
            out["judgment"].update(decisive_evidence=["확인한 반대 증거"], change_conditions=[{"event_or_question": "현금", "observation": "개선", "why_it_matters": "기대",
                      "response": "확대", "evidence_ids": [f"d2-r0-{len(self.texts['d2'])}"]}])
        elif stage.startswith("research-q") or stage.startswith("research-challenge-") or stage.startswith("research-postwrite-challenge-"):
            qid = "q1" if "q1" in stage else "q2"
            sid = "d3" if "challenge-" in stage else "d1" if qid == "q1" else "d2"
            context = json.loads(payload["prompt"])
            self.assertEqual(context["baseline"]["sources"], {})  # no other researcher's reads
            if stage.endswith("-0"):
                out = {"decision_reason": "원문 확인", "reads": [{"source_id": sid}], "searches": [], "memo": None}
            else:
                out = {"decision_reason": "필요 원문 확보", "reads": [], "searches": [], "memo": self.memo(qid, sid)}
        elif stage.endswith("-facts"):
            out = {"assessment": "근거 확인", "issues": []}
        elif stage.endswith("-investor"):
            self.assertNotIn('"memos"', payload["prompt"])
            self.assertNotIn('"routing"', payload["prompt"])
            out = {"market_state_understood": "변화", "author_view_understood": "선별", "current_response_understood": "보류",
                   "change_conditions_understood": "현금", "verdict": "readable", "issues": []}
        else:
            quote = self.texts["d3"]
            paragraphs = [{"id": f"p{i}", "text": quote + " 기존 보유는 유지하며 신규 진입은 현금흐름 개선까지 보류한다.",
                           "sources": [{"source_id": f"d3-r0-{len(quote)}", "anchor": "반대 증거", "quote": quote}]} for i in range(3)]
            out = {"title": "실제 반대 근거를 반영한 판단", "opening": paragraphs[0], "sections": [
                   {"heading": "지난주 변화", "paragraphs": [paragraphs[1]]}, {"heading": "현재 대응", "paragraphs": [paragraphs[2]]}]}
        return {"text": dumps(out), "usage": {}, "cost_usd": 0, "engine": "test"}

    def test_challenge_retrieves_new_original_and_changes_writer_context(self):
        result = run(self.directory, model_call=self.model)
        self.assertEqual(result["status"], "completed")
        packet = json.loads((self.directory / "research-packet.json").read_text())
        self.assertIn(f"d3-r0-{len(self.texts['d3'])}", packet["sources"])
        self.assertNotIn(f"d1-r0-{len(self.texts['d1'])}", packet["sources"])
        writer = next(p for stage, p in self.calls if stage == "judged")
        self.assertIn(self.texts["d3"], writer["prompt"])
        self.assertNotIn(self.texts["d1"], writer["prompt"])

        director = json.loads(next(p for stage, p in self.calls if stage == "research-decision")["prompt"])
        self.assertIn("q1", director["memos"])
        self.assertIn("challenge-0-q1", director["memos"])
        self.assertEqual(director["memos"]["q1"]["claims"][0]["id"], "q1/q1-c1")
        events = json.loads((self.directory / "research/events.json").read_text())
        self.assertTrue(any(e["kind"] == "research_request" for e in events))
        self.assertIn("research.html", (self.directory / "index.html").read_text())
        count = len(self.calls)
        run(self.directory, model_call=self.model)
        self.assertEqual(len(self.calls), count)

    def test_missing_citation_is_repaired_without_rewriting_prose(self):
        original = {}
        def missing_citation(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-judged-source-repair":
                self.assertEqual(payload["effort"], "medium")
                paragraph = json.loads(payload["prompt"])["paragraphs"][0]
                self.assertEqual(paragraph["id"], "p1")
                quote = self.texts["d3"]
                return {"text": dumps({"paragraphs": [{"paragraph_id": "p1", "sources": [{
                    "source_id": f"d3-r0-{len(quote)}", "anchor": "반대 증거", "quote": quote}]}], "unresolved": ["의미는 원문과 대조해 판정해야 한다"]})}
            result = self.model(payload, timeout, cancelled)
            if payload["job"] == "weekly-reader-judged":
                report = json.loads(result["text"])
                report["sections"][0]["paragraphs"][0]["sources"] = []
                original.update(copy.deepcopy(report))
                result["text"] = dumps(report)
            return result
        result = run(self.directory, model_call=missing_citation)
        self.assertTrue(result["automatic_checks_passed"])
        repaired = json.loads((self.directory / "judged.json").read_text())
        self.assertTrue(repaired["sections"][0]["paragraphs"][0]["sources"])
        repaired["sections"][0]["paragraphs"][0]["sources"] = []
        self.assertEqual(repaired, ReaderBrief.model_validate(original).model_dump(mode="json"))
        self.assertFalse((self.directory / "calls/judged-structure-repair.json").exists())
        factual = next(payload for stage, payload in self.calls if stage == "judged-facts")
        self.assertIn("의미는 원문과 대조해 판정해야 한다", factual["prompt"])
        self.assertEqual(json.loads((self.directory / "judged-checks.json").read_text())["mechanical"]["blocking"], 0)

    def test_cutoff_reference_and_search_read_boundary(self):
        desk = ResearchDesk(self.directory, self.packet, None)
        self.assertNotIn("d4", desk.documents)
        self.assertNotIn("d5", desk.documents)
        found = desk.search(SearchRequest(query="태그인물"))
        self.assertEqual(found["candidates"][0]["source_id"], "d2")
        with self.assertRaisesRegex(ValueError, "읽지 않은"):
            desk.validate_memo(ResearchMemo.model_validate(self.memo("q1", "d2")), "q1")
        desk.read(ReadRequest(source_id="d2"), "q1")
        memo = ResearchMemo.model_validate(self.memo("q1", "d2"))
        desk.validate_memo(memo, "q1")
        memo.claims[0].citations[0].quote = "원문에 없는 거짓 인용입니다"
        with self.assertRaisesRegex(ValueError, "원문에 없는"):
            desk.validate_memo(memo, "q1")
        self.assertEqual(desk.search(SearchRequest(query="수요", until="2026-09-09"))["candidates"], [])

    def test_document_ids_resolve_only_to_an_exact_actually_read_span(self):
        desk = ResearchDesk(self.directory, self.packet, None)
        memo = ResearchMemo.model_validate(self.memo("q1", "d2"))
        for claim in memo.claims:
            claim.citations[0].source_id = "d2"
        # Finding a snippet does not grant citation eligibility.
        desk.search(SearchRequest(query="현금흐름"))
        with self.assertRaisesRegex(ValueError, "읽지 않은"):
            desk.validate_memo(memo, "q1")

        desk.read(ReadRequest(source_id="d2"), "q1")
        desk.validate_memo(memo, "q1")
        self.assertEqual(memo.claims[0].citations[0].source_id, f"d2-r0-{len(self.texts['d2'])}")
        self.assertTrue(any(e["kind"] == "citation_resolved" for e in desk.events))
        memo.claims[0].citations[0].source_id = "d2"
        memo.claims[0].citations[0].quote = "읽은 원문에는 없는 가짜 주장입니다"
        with self.assertRaisesRegex(ValueError, "읽지 않은"):
            desk.validate_memo(memo, "q1")

    def test_whitespace_alignment_preserves_raw_characters_and_rejects_word_changes(self):
        from pipeline.weekly.research import exact_whitespace_quote
        text = "9일 오전\u00a011시께 발표한다.\n\n다음 날에는\u00a030년물 입찰이 있다."
        self.assertEqual(exact_whitespace_quote(text, "9일 오전 11시께 발표한다."), "9일 오전\u00a011시께 발표한다.")
        self.assertIsNone(exact_whitespace_quote(text, "10일 오전 11시께 발표한다."))
        self.assertIsNone(exact_whitespace_quote(text, "9일 오전 11시에 발표한다."))

    def test_material_gap_cannot_become_automatic_pass(self):
        self.material = ["현재 대응 강도를 정할 실제 기대 자료 부족"]
        result = run(self.directory, model_call=self.model)
        self.assertFalse(result["automatic_checks_passed"])
        self.assertEqual(result["unresolved_material"], self.material)

    def test_routing_tamper_is_rejected_before_model(self):
        atomic_write(self.directory / "routing.json", "{}")
        with self.assertRaisesRegex(ValueError, "연구 입력"):
            run(self.directory, model_call=self.model)
        self.assertEqual(self.calls, [])

    def test_resume_replays_tools_without_repeating_successful_model_calls(self):
        def interrupted(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-research-challenge":
                raise TimeoutError("interrupted")
            return self.model(payload, timeout, cancelled)
        with self.assertRaises(TimeoutError):
            run(self.directory, model_call=interrupted)
        run(self.directory, model_call=self.model)
        self.assertEqual(sum(s == "research-q1-0" for s, _ in self.calls), 1)
        self.assertEqual(sum(s == "research-agenda" for s, _ in self.calls), 1)

    def test_failed_stage_can_change_with_history_while_completed_calls_stay_exact(self):
        def interrupted(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-research-challenge":
                raise TimeoutError("interrupted")
            return self.model(payload, timeout, cancelled)
        with self.assertRaises(TimeoutError):
            run(self.directory, model_call=interrupted)
        from unittest.mock import patch
        from pipeline.weekly import research_prompts
        with patch.object(research_prompts, "CHALLENGE", research_prompts.CHALLENGE + "\nCheck primary sources."):
            run(self.directory, model_call=self.model)
        self.assertEqual(sum(s == "research-agenda" for s, _ in self.calls), 1)
        history = list((self.directory / "calls/history").glob("research-challenge-*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0].read_text())["error"], "interrupted")

    def test_postwrite_research_preserves_prior_draft_evidence_and_context(self):
        self.manifest["request"].update(completion_engine="codex-exec", completion_model="test-completion")
        atomic_write(self.directory / "manifest.json", dumps(self.manifest))
        def needs_research(payload, timeout, cancelled):
            result = self.model(payload, timeout, cancelled)
            if payload["job"] == "weekly-reader-judged-facts":
                result["text"] = dumps({"assessment": "추가 근거", "issues": [{"severity": "blocking", "location": "p1",
                                        "reason": "반론 누락", "requested_change": "재조사"}]})
            return result
        result = run(self.directory, model_call=needs_research)
        self.assertEqual(result["status"], "completed")
        postwrite = next(p for s, p in self.calls if s == "research-postwrite-challenge")
        feedback = json.loads(postwrite["prompt"])["feedback"]
        self.assertIn("draft", feedback)
        self.assertIn("previous_decision", feedback)
        old_id = f"d2-r0-{len(self.texts['d2'])}"
        self.assertIn(old_id, (self.directory / "judged-evidence.html").read_text())
        self.assertNotIn(old_id, json.loads((self.directory / "reviewed-packet.json").read_text())["sources"])
        self.assertIn('href="judged-evidence.html', (self.directory / "judged.html").read_text())
        for stage, payload in self.calls:
            if stage.startswith("reviewed"):
                self.assertEqual(payload["engine"], "codex-exec")
                self.assertEqual(payload["model"], "test-completion")
            else:
                self.assertNotIn("engine", payload)
                self.assertEqual(payload["model"], "opus")

    def test_selection_repair_keeps_judgment_and_revalidates_source_ids(self):
        original = {}
        def repair_selection(payload, timeout, cancelled):
            stage = payload["job"]
            if stage.endswith("selection-repair-v1"):
                self.assertEqual(payload["effort"], "medium")
                context = json.loads(payload["prompt"])
                self.assertIn("source_costs", context)
                selected = [sid for sid in context["previous_decision"]["writing_source_ids"] if sid != "unread"]
                return {"text": dumps({"disposition_updates": [], "writing_source_ids": selected,
                                       "judgment": None, "additional_material_gaps": []})}
            result = self.model(payload, timeout, cancelled)
            if stage == "weekly-reader-judged-facts":
                result["text"] = dumps({"assessment": "추가 근거", "issues": [{"severity": "blocking", "location": "p1",
                                        "reason": "반론 누락", "requested_change": "재조사"}]})
            if stage == "weekly-reader-research-revised-decision":
                decision = json.loads(result["text"])
                original.update(copy.deepcopy(decision["judgment"]))
                decision["writing_source_ids"].append("unread")
                result["text"] = dumps(decision)
            return result
        result = run(self.directory, model_call=repair_selection)
        self.assertTrue(result["automatic_checks_passed"])
        decision = json.loads((self.directory / "research/revised-decision.json").read_text())
        self.assertNotIn("unread", decision["writing_source_ids"])
        from models.weekly_reader import Judgment
        self.assertEqual(decision["judgment"], Judgment.model_validate(original).model_dump(mode="json"))

    def test_action_budget_does_not_silently_manufacture_completion(self):
        def search_forever(*args):
            return ResearchStep(decision_reason="계속 검색", searches=[SearchRequest(query="금리")])
        desk = ResearchDesk(self.directory, self.packet, search_forever)
        from models.weekly_research import QuestionBrief
        with self.assertRaisesRegex(ValueError, "예산 종료"):
            desk.investigate(QuestionBrief.model_validate(self.question("q1")), "q1", rounds=1)
        self.assertFalse(desk.memos)

    def test_invalid_reviewer_query_returns_rejection_and_allows_direct_read(self):
        contexts = []
        def model(stage, system, prompt, schema):
            context = json.loads(prompt)
            contexts.append(context)
            if len(contexts) == 1:
                return ResearchStep(decision_reason="직접 읽기", reads=[ReadRequest(source_id="d3")])
            return ResearchStep(decision_reason="확보 완료", memo=ResearchMemo.model_validate(self.memo("q1", "d3")))
        desk = ResearchDesk(self.directory, self.packet, model)
        from models.weekly_research import QuestionBrief
        request = {"query": "가" * 170, "evidence_needed": "d3 직접 읽기"}
        desk.investigate(QuestionBrief.model_validate(self.question("q1")), "followup", request, rounds=1)
        self.assertEqual(contexts[0]["followup"], request)
        self.assertIn("160", contexts[0]["tool_results"][0]["result"]["error"])
        self.assertIn("q1", desk.memos)

    def test_citation_repair_batches_all_errors_without_rewriting_claims(self):
        contexts = []
        bad = self.memo("q1", "d3")
        for c in bad["claims"]:
            c["citations"][0]["quote"] = "틀리게 인용한 문장입니다"
        def model(stage, system, prompt, schema):
            context = json.loads(prompt)
            contexts.append(context)
            if schema.__name__ == "CitationRepairs":
                self.assertEqual(len(context["errors"]), 2)
                return schema(repairs=[{"claim_id": c["id"], "citations": self.memo("q1", "d3")["claims"][0]["citations"]} for c in bad["claims"]])
            if len(contexts) == 1:
                return ResearchStep(decision_reason="원문", reads=[ReadRequest(source_id="d3")])
            return ResearchStep(decision_reason="메모", memo=ResearchMemo.model_validate(bad))
        desk = ResearchDesk(self.directory, self.packet, model)
        from models.weekly_research import QuestionBrief
        desk.investigate(QuestionBrief.model_validate(self.question("q1")), "q1", rounds=1)
        self.assertEqual(desk.memos["q1"]["answer"], bad["answer"])
        self.assertEqual(len(contexts), 3)

    def test_empty_profiles_and_blog_url_keys_are_retrieval_hints(self):
        routing_path = self.directory / "routing.json"
        routing = json.loads(routing_path.read_text())
        routing["profiles"].extend([
            {"kind": "blog", "key": "https://blog.naver.com/researcher", "digest": "기업 금리", "insights": None, "created_at": "2026-09-15"},
            {"kind": "telegram", "key": "channeld1", "digest": None, "insights": None, "created_at": "2026-09-15"}])
        atomic_write(routing_path, dumps(routing))
        desk = ResearchDesk(self.directory, self.packet, None)
        desk.discover()
        desk.search(SearchRequest(query="금리"))
        self.assertIn(("blog", "researcher"), desk.profiles)
        from pipeline.weekly.research import channel_key
        self.assertEqual(channel_key({"source_type": "blog", "url": "https://blog.naver.com/PostView.naver?blogId=researcher&logNo=1"}), "researcher")

    def test_undated_frozen_primary_sources_reach_specialist_catalog(self):
        source = {"meta": {"title": "Company official results", "source_type": "official", "published_at": None},
                  "text": "Customer prepayments are included in operating cash flows.", "raw_file": "evidence/primary.json"}
        atomic_write(self.directory / source["raw_file"], dumps(source))
        atomic_write(self.directory / "external-catalog.json", dumps({"provider-01": source}))
        calls = []
        def review(stage, system, prompt, schema):
            calls.append(json.loads(prompt))
            return schema(assessment="check originals", requests=[])
        desk = ResearchDesk(self.directory, self.packet, review)
        from models.weekly_research import ResearchAgenda
        desk.agenda = ResearchAgenda(market_puzzle="puzzle", questions=[self.question("q1"), self.question("q2")], deferred=[])
        desk.review("challenge")
        self.assertEqual(calls[0]["available_primary_catalog"][0]["source_id"], "provider-01")
        self.assertEqual(calls[0]["sources"], {})  # catalogue is not read evidence

    def test_oversize_read_is_rejected_before_citation_eligibility(self):
        steps = []
        def request_large_reads(stage, system, prompt, schema):
            context = json.loads(prompt)
            steps.append(context)
            return ResearchStep(decision_reason="긴 원문", reads=[ReadRequest(source_id="d1", length=18000)] * 6)
        desk = ResearchDesk(self.directory, self.packet, request_large_reads)
        desk.documents["d1"]["text"] = "아" * 18000
        from models.weekly_research import QuestionBrief
        with self.assertRaisesRegex(ValueError, "예산 종료"):
            desk.investigate(QuestionBrief.model_validate(self.question("q1")), "q1", rounds=2)
        self.assertTrue(any(ev["kind"] == "read" and ev.get("error") for ev in desk.events))
        self.assertLess(len(dumps(steps[-1])), 165000)


if __name__ == "__main__":
    unittest.main()

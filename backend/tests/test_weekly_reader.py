import copy
import fcntl
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from models.weekly_reader import ComparisonRequest, ReaderBrief
from pipeline.weekly.reader_experiment import run
from pipeline.weekly.reader_fork import fork
from pipeline.weekly.reader_packet import add_series, prepare
from pipeline.weekly.reader_render import write_brief, write_support
from pipeline.weekly.reader_review import check, plain, publishable
from pipeline.weekly.store import atomic_write, digest, dumps
from pipeline.weekly.worker import Cancelled


class ReaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.request = ComparisonRequest(request_key="test", source_run_id="a" * 32,
                                         week_start="2026-09-07", week_end="2026-09-11",
                                         outlook_start="2026-09-14", outlook_end="2026-09-18")
        self.quote = "수요는 증가했지만 현금흐름은 여전히 약하다."
        self.packet = {"period": {k: str(getattr(self.request, k)) for k in ("week_start", "week_end", "outlook_start", "outlook_end")},
                       "cutoff": "2026-09-15T00:00:00Z", "sources": {"d1": {"meta": {"title": "현금흐름 <script>"}, "kind": "document",
                                                                          "text": self.quote, "raw_file": "evidence/d1.json"}},
                       "metrics": {"m0001": {"source_id": "d1", "value": 1.25, "formatted": "1.25%"}},
                       "charts": {}, "gaps": [], "coverage": {"company": ["d1"]}}
        self.brief = ReaderBrief.model_validate({"title": "수요 성장과 현금의 간극", "opening": self.paragraph(0),
                                                "sections": [{"heading": "지난주", "paragraphs": [self.paragraph(1)]},
                                                             {"heading": "이번 대응", "paragraphs": [self.paragraph(2)]}]})
        self.calls = []
        self.investor = {"market_state_understood": "수요 증가", "author_view_understood": "선별 보유", "current_response_understood": "신규 진입 보류",
                         "change_conditions_understood": "현금 개선", "verdict": "readable", "issues": []}
        atomic_write(self.directory / "packet.json", dumps(self.packet))
        atomic_write(self.directory / "selection.json", dumps({"areas": {"company": ["d1"]}}))
        atomic_write(self.directory / "evidence/d1.json", dumps({"text": self.quote}))
        atomic_write(self.directory / "manifest.json", dumps({"request": self.request.model_dump(mode="json"), "packet_sha256": digest(self.packet),
                                                              "status": "prepared", "document_count": 1}))

    def paragraph(self, number):
        return {"id": f"p{number}", "text": "수요는 증가했지만 현금흐름은 약하다. 기존 보유는 유지하고 신규 진입은 현금 개선까지 보류한다.",
                "sources": [{"source_id": "d1", "anchor": "수요는 증가했지만", "quote": self.quote}]}

    def model(self, payload, timeout, cancelled):
        stage = payload["job"].removeprefix("weekly-reader-")
        self.calls.append((stage, payload))
        if cancelled():
            raise Cancelled("cancel")
        if stage in {"judgment", "reviewed-judgment"}:
            out = {k: "PRIVATE_JUDGMENT" for k in ("week_in_review", "market_state", "central_question", "preferred_explanation", "strongest_counterargument", "current_response", "opportunity_cost")}
            out.update(decisive_evidence=["d1: 현금흐름"], change_conditions=[{"event_or_question": "현금", "observation": "개선", "why_it_matters": "자금", "response": "확대", "evidence_ids": ["d1"]}])
        elif stage.endswith("-facts"):
            out = {"assessment": "bounded", "issues": []}
            if stage == "judged-facts":
                out["issues"] = [{"severity": "blocking", "location": "p1", "reason": "반대 근거 누락", "requested_change": "현금 제약을 설명"}]
        elif stage.endswith("-investor"):
            out = self.investor
        else:
            out = self.brief.model_dump(mode="json")
        return {"text": dumps(out), "usage": {"input": 1}, "engine": "test", "cost_usd": 0}

    def test_single_report_keeps_review_pipeline_without_comparison_baseline(self):
        manifest = json.loads((self.directory / "manifest.json").read_text())
        manifest["request"]["workflow"] = "briefing"
        self.packet["workflow"] = "briefing"
        manifest["packet_sha256"] = digest(self.packet)
        atomic_write(self.directory / "packet.json", dumps(self.packet))
        atomic_write(self.directory / "manifest.json", dumps(manifest))
        result = run(self.directory, model_call=self.model)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["automatic_checks_passed"])
        self.assertEqual([s for s, _ in self.calls], ["judgment", "judged", "judged-facts", "judged-investor", "reviewed-judgment", "reviewed", "reviewed-facts", "reviewed-investor"])
        self.assertFalse((self.directory / "single.html").exists())
        self.assertFalse((self.directory / "review.html").exists())
        self.assertIn('href="reviewed.html"', (self.directory / "index.html").read_text())
        for f in ["index.html", "reviewed.html", "evidence.html", "audit.html"]:
            self.assertNotIn("세 브리핑 비교", (self.directory / f).read_text())
        count = len(self.calls)
        run(self.directory, model_call=self.model)
        self.assertEqual(len(self.calls), count)

    def test_read_review_rewrite_and_final_review_with_isolated_investor(self):
        result = run(self.directory, model_call=self.model)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["automatic_checks_passed"])
        self.assertIsNone(result["winner"])
        self.assertEqual(result["expert_quality"], "not_evaluated")
        stages = [s for s, _ in self.calls]
        self.assertEqual(stages, ["single", "judgment", "judged", "judged-facts", "judged-investor", "reviewed-judgment", "reviewed", "reviewed-facts", "reviewed-investor"])
        for stage, payload in self.calls:
            if stage.endswith("-investor"):
                self.assertNotIn("PRIVATE_JUDGMENT", payload["prompt"])
                self.assertNotIn("requested_change", payload["prompt"])
                self.assertEqual(payload["prompt"], plain(self.brief, self.packet))
            if stage == "reviewed":
                self.assertNotIn("requested_change", payload["prompt"])
                self.assertNotIn("내부 초안", payload["prompt"])
        self.assertIn("PRIVATE_JUDGMENT", (self.directory / "audit.html").read_text())
        self.assertNotIn("PRIVATE_JUDGMENT", (self.directory / "reviewed.html").read_text())
        n = len(self.calls)
        run(self.directory, model_call=self.model)
        self.assertEqual(len(self.calls), n)

    def test_failed_call_resumes_without_repeating_successful_stages(self):
        def interrupted(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-judgment":
                raise TimeoutError("interrupted")
            return self.model(payload, timeout, cancelled)
        with self.assertRaises(TimeoutError):
            run(self.directory, model_call=interrupted)
        self.assertTrue((self.directory / "single.html").exists())
        self.assertEqual(json.loads((self.directory / "manifest.json").read_text())["status"], "partial")
        run(self.directory, model_call=self.model)
        self.assertEqual(sum(s == "single" for s, _ in self.calls), 1)

    def test_cancel_and_lock_do_not_launch_calls(self):
        (self.directory / "cancel.requested").touch()
        with self.assertRaises(Cancelled):
            run(self.directory, model_call=self.model)
        self.assertFalse(self.calls)
        (self.directory / "cancel.requested").unlink()
        with (self.directory / ".run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "이미 진행"):
                run(self.directory, model_call=self.model)

    def test_unsealed_preparation_cannot_start_even_with_a_packet(self):
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["status"] = "preparing"
        atomic_write(path, dumps(manifest))
        with self.assertRaisesRegex(ValueError, "입력 준비"):
            run(self.directory, model_call=self.model)
        self.assertFalse(self.calls)

    def test_changed_cached_model_output_is_rejected_on_resume(self):
        def interrupted(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-judgment":
                raise TimeoutError("interrupted")
            return self.model(payload, timeout, cancelled)
        with self.assertRaises(TimeoutError):
            run(self.directory, model_call=interrupted)
        path = self.directory / "calls/single.json"
        cached = json.loads(path.read_text())
        cached["parsed"]["title"] = "tampered"
        atomic_write(path, dumps(cached))
        with self.assertRaisesRegex(ValueError, "모델 출력"):
            run(self.directory, model_call=self.model)

    def test_host_validation_change_is_logged_and_previous_exports_preserved(self):
        def interrupted(payload, timeout, cancelled):
            if payload["job"] == "weekly-reader-judgment":
                raise TimeoutError("interrupted")
            return self.model(payload, timeout, cancelled)
        with self.assertRaises(TimeoutError):
            run(self.directory, model_call=interrupted)
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["execution_contract"] = "previous-contract"
        atomic_write(path, dumps(manifest))
        result = run(self.directory, model_call=self.model)
        self.assertEqual(result["contract_changes"][0]["previous"], "previous-contract")
        self.assertTrue((self.directory / "previous-exports/previous-con/single.json").exists())
        self.assertEqual(sum(s == "single" for s, _ in self.calls), 1)

    def test_packet_and_archived_source_tampering_are_rejected(self):
        run(self.directory, model_call=self.model)
        atomic_write(self.directory / "evidence/d1.json", "changed")
        with self.assertRaisesRegex(ValueError, "보관 원문"):
            run(self.directory, model_call=self.model)
        packet = copy.deepcopy(self.packet)
        packet["cutoff"] = "changed"
        atomic_write(self.directory / "packet.json", dumps(packet))
        with self.assertRaisesRegex(ValueError, "동결된"):
            run(self.directory, model_call=self.model)

    def test_metric_tokens_and_exact_quote_bindings(self):
        brief = self.brief.model_copy(deep=True)
        brief.opening.text += " 상승률은 {{m0001}}다."
        self.assertFalse(check(brief, self.packet)["blocking"])
        self.assertIn("1.25%다", plain(brief, self.packet))
        brief.opening.text += " {{m0001}}% {{m9000}}"
        brief.opening.sources[0].quote = "실제 원문에 없는 인용입니다."
        brief.sections[0].paragraphs[0].id = "p0"
        result = check(brief, self.packet)
        self.assertGreaterEqual(result["blocking"], 4)

    def test_residual_issues_cannot_pass_as_reviewed(self):
        self.assertFalse(publishable({"blocking": 0}, None, self.investor))
        factual = {"issues": [{"severity": "blocking"}]}
        self.assertFalse(publishable({"blocking": 0}, factual, self.investor))
        self.assertFalse(publishable({"blocking": 1}, {"issues": []}, self.investor))
        self.assertFalse(publishable({"blocking": 0}, {"issues": []}, dict(self.investor, verdict="rewrite")))

    def test_future_change_of_view_is_not_an_internal_revision_log(self):
        brief = self.brief.model_copy(deep=True)
        brief.opening.text += " 자금 조달이 악화되면 현재의 보유 판단을 철회한다."
        self.assertFalse(check(brief, self.packet)["blocking"])
        brief.opening.text += " 이전 초안의 오류를 정정한다."
        self.assertTrue(check(brief, self.packet)["blocking"])
        brief.opening.text = "여기서 앞서 유지하던 해석 하나를 접는다. 수요는 증가했지만 현금흐름이 약하다."
        self.assertTrue(check(brief, self.packet)["blocking"])

    def test_c_repairs_unsupported_self_history_before_final_reviews(self):
        def with_history(payload, timeout, cancelled):
            result = self.model(payload, timeout, cancelled)
            if payload["job"] == "weekly-reader-reviewed":
                report = json.loads(result["text"])
                report["sections"][0]["heading"] = "물가가 내 전제를 무너뜨렸다"
                result["text"] = dumps(report)
            return result
        result = run(self.directory, model_call=with_history)
        self.assertTrue(result["automatic_checks_passed"])
        stages = [s for s, _ in self.calls]
        self.assertIn("reviewed-structure-repair", stages)
        self.assertLess(stages.index("reviewed-structure-repair"), stages.index("reviewed-facts"))
        self.assertNotIn("내 전제를", (self.directory / "reviewed.html").read_text())

    def test_fork_reuses_exact_writing_but_repeats_reviews_without_changing_source(self):
        run(self.directory, model_call=self.model)
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            shutil.copytree(self.directory, source)
            before = (source / "manifest.json").read_bytes()
            directory = fork(source, "new-review")
            self.calls.clear()
            result = run(directory, model_call=self.model)
            self.assertEqual(result["inherited_from"], "source")
            self.assertEqual([s for s, _ in self.calls], ["judged-facts", "judged-investor", "reviewed-judgment", "reviewed", "reviewed-facts", "reviewed-investor"])
            self.assertEqual(before, (source / "manifest.json").read_bytes())
            self.assertEqual((source / "packet.json").read_bytes(), (directory / "packet.json").read_bytes())
            with self.assertRaises(FileExistsError):
                fork(source, "new-review")
            with_reviews = fork(source, "with-reviews", reuse_reviews=True)
            self.calls.clear()
            run(with_reviews, model_call=self.model)
            self.assertEqual([s for s, _ in self.calls], ["reviewed-judgment", "reviewed", "reviewed-facts", "reviewed-investor"])
            with_draft = fork(source, "with-draft", reuse_draft=True)
            self.calls.clear()
            run(with_draft, model_call=self.model)
            self.assertEqual([s for s, _ in self.calls], ["reviewed-facts", "reviewed-investor"])

    def test_render_escapes_text_and_keeps_typed_units(self):
        brief = self.brief.model_copy(deep=True)
        brief.opening.text += " <script>alert(1)</script> {{m0001}}"
        write_brief(self.directory, "test", brief, self.packet)
        text = (self.directory / "test.html").read_text()
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("1.25%", text)
        self.assertNotIn("%%", text)

    def test_evaluation_identity_changes_with_text_and_preserves_entered_scores(self):
        manifest = run(self.directory, model_call=self.model)
        path = self.directory / "expert-review.json"
        evaluation = json.loads(path.read_text())
        old_set = evaluation["review_set_sha256"]
        evaluation["reviewer"] = "human reviewer"
        atomic_write(path, dumps(evaluation))
        brief = self.brief.model_copy(deep=True)
        brief.title = "Different candidate with the same evidence"
        write_brief(self.directory, "reviewed", brief, self.packet)
        write_support(self.directory, self.packet, manifest)
        self.assertEqual(json.loads(path.read_text()), evaluation)
        new_template = next(self.directory.glob("expert-review-*.json"))
        new_set = json.loads(new_template.read_text())["review_set_sha256"]
        self.assertNotEqual(old_set, new_set)
        self.assertIn("weekly-reader-review-" + new_set, (self.directory / "review.html").read_text())

    def test_weekly_return_includes_previous_close_and_preserves_missing_dates(self):
        packet = {"sources": {}, "metrics": {}, "charts": {}, "coverage": {}, "gaps": []}
        points = [{"date": "2026-09-04", "value": 100}, {"date": "2026-09-08", "value": 110}, {"date": "2026-09-10", "value": 120}]
        item = {"id": "s-test", "meta": {"title": "test", "metric_kind": "price", "unit": "USD / share"}, "data": {"points": points}}
        add_series(packet, item, self.directory, self.request)
        result = next(m for m in packet["metrics"].values() if m["definition"] == "return_pct")
        self.assertAlmostEqual(result["value"], 20)
        self.assertEqual(result["start"], "2026-09-04")
        self.assertEqual(result["end"], "2026-09-10")
        self.assertFalse(result["complete_week"])
        self.assertEqual(result["observations"], 3)
        self.assertTrue(packet["gaps"])

    def test_yield_change_is_percentage_points_and_stale_baseline_is_excluded(self):
        packet = {"sources": {}, "metrics": {}, "charts": {}, "coverage": {}, "gaps": []}
        item = {"id": "s-yield", "meta": {"title": "yield", "metric_kind": "yield", "unit": "percent"},
                "data": {"points": [{"date": "2026-09-04", "value": 4}, {"date": "2026-09-11", "value": 4.25}]}}
        add_series(packet, item, self.directory, self.request)
        self.assertEqual(packet["metrics"]["m0002"]["formatted"], "0.25%p")
        item["id"] = "s-stale"
        item["data"]["points"][0]["date"] = "2026-07-01"
        add_series(packet, item, self.directory, self.request)
        self.assertNotIn("s-stale", packet["sources"])

    def test_twenty_observation_return_metadata(self):
        packet = {"sources": {}, "metrics": {}, "charts": {}, "coverage": {}, "gaps": []}
        points = [{"date": (date(2026, 8, 10) + timedelta(days=i)).isoformat(), "value": 100 + i} for i in range(33)]
        item = {"id": "s-test", "meta": {"title": "test", "metric_kind": "price", "unit": "USD / share"}, "data": {"points": points}}
        add_series(packet, item, self.directory, self.request)
        m = next(m for m in packet["metrics"].values() if m["definition"] == "twenty_return")
        self.assertEqual(m["observations"], 21)
        self.assertEqual(m["start"], "2026-08-22")

    def test_preparation_rejects_target_weekly_and_derived_summary(self):
        from types import SimpleNamespace
        store = SimpleNamespace(get=lambda rid: {"checkpoint": {"corpus_sha256": "hash"}, "config": {"cutoff": "2026-09-15T00:00:00Z"}},
                                directory=lambda rid: self.directory)
        for index, meta in enumerate(({"url": "https://notion.site/3da9e403cb628080a1fed604f8542436"}, {"content_kind": "derived_summary"})):
            with patch("pipeline.weekly.reader_packet.Evidence") as evidence:
                evidence.return_value.file_hash.return_value = "hash"
                evidence.return_value.get.return_value = {"kind": "document", "meta": meta, "text": self.quote, "sha256": "hash"}
                with self.assertRaises(ValueError):
                    prepare(self.request.model_copy(update={"request_key": f"blocked{index}"}), {"areas": {"test": ["d1"]}}, store=store, root=self.directory)


if __name__ == "__main__":
    unittest.main()

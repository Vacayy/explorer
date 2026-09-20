"""Persistence and authorization boundaries of the discovery application workflow."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.market_analysis import AnalysisSpec
from models.discovery import SaveNote
from pipeline.market_analysis.discovery_service import DiscoveryService
from pipeline.market_analysis.discovery_store import DiscoveryStore
from pipeline.market_analysis.store import Conflict, RunStore


class AnalysisFixture:
    def __init__(self, path):
        self.store = RunStore(path)

    def create(self, request):
        return self.store.public(self.store.create(request)[0])


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.analysis = AnalysisFixture(self.root / "analysis")
        self.service = DiscoveryService(self.analysis, self.root / "discovery", self.root / "missing-source.sqlite",
            preparer=lambda *args, **kwargs: {"status": "completed", "items": []})
        self.service.start = lambda: None
        self.run = self.analysis.create({"question": "추세가 유지되는 기업", "request_key": "source-0000001"})
        self.spec = AnalysisSpec(mode="catalog", strategy_conditions=[{"strategy_id": "sma_bullish_order"}]).model_dump(mode="json")
        self.analysis.store.mutate(self.run["id"], lambda s: s.update(status="partial", phase="finished", spec=self.spec,
            result={"spec": self.spec, "as_of": "2026-09-18", "snapshot_id": "a" * 32,
                    "verification": {"status": "matched"}, "warnings": ["자료 공백"],
                    "items": [{"code": "000001", "name": "테스트", "checks": {"sma_bullish_order": {"status": "pass"}}}]}))
        self.save = {"source_run_id": self.run["id"], "name": "추세", "purpose": "후속 조사", "date_policy": "latest", "request_key": "save-0000001"}

    def tearDown(self):
        self.service.stop()
        self.temp.cleanup()

    def case(self, key="case-000001"):
        return self.service.create_case({"run_id": self.run["id"], "stock_code": "000001", "question": "왜 관심인가?", "request_key": key})

    def test_concurrent_save_once_and_changed_retry_conflicts(self):
        with ThreadPoolExecutor(4) as pool:
            records = list(pool.map(lambda _: self.service.save_strategy(self.save), range(8)))
        self.assertEqual(len({x["id"] for x in records}), 1)
        self.assertEqual(len(self.service.store.list("strategy")), 1)
        with self.assertRaises(Conflict):
            self.service.save_strategy({**self.save, "name": "다른 전략"})

    def test_versions_preserve_definition_and_detect_stale_edit(self):
        saved = self.service.save_strategy(self.save)
        original = copy.deepcopy(saved["versions"][0])
        request = {**self.save, "name": "다음 버전", "expected_version": 1, "request_key": "version-0002"}
        updated = self.service.save_strategy(request, saved["id"])
        self.assertEqual(updated["versions"][0], original)
        self.assertEqual(updated["current_version"], 2)
        with self.assertRaises(Conflict):
            self.service.save_strategy({**request, "request_key": "version-0003"}, saved["id"])
        reopened = DiscoveryStore(self.root / "discovery")
        self.assertEqual(reopened.get("strategy", saved["id"]), updated)

    def test_rerun_retry_keeps_resolved_version_after_edit(self):
        saved = self.service.save_strategy(self.save)
        run = self.service.run_strategy(saved["id"], {"version": None, "request_key": "run-00000001"})
        self.service.save_strategy({**self.save, "date_policy": "fixed", "expected_version": 1,
                                    "request_key": "version-0002"}, saved["id"])
        retried = self.service.run_strategy(saved["id"], {"version": None, "request_key": "run-00000001"})
        self.assertEqual(run["id"], retried["id"])
        self.assertEqual(retried["saved_strategy"]["version"], 1)
        request = self.analysis.store.read(run["id"])["_request"]
        self.assertIsNone(request["spec"]["as_of"])
        fixed = self.service.run_strategy(saved["id"], {"request_key": "run-fixed-001"})
        payload = self.analysis.store.read(fixed["id"])["_request"]
        self.assertEqual(payload["parent_run_id"], self.run["id"])
        self.assertEqual(payload["spec_patch"], {})
        self.assertEqual(payload["date_policy"], "same")

    def test_requires_independent_verification_and_actual_candidate(self):
        with self.assertRaises(ValueError):
            self.service.create_case({"run_id": self.run["id"], "stock_code": "999999", "question": "왜", "request_key": "case-invalid"})
        self.analysis.store.mutate(self.run["id"], lambda s: s["result"].update(verification={"status": "mismatch"}))
        with self.assertRaises(Conflict):
            self.service.save_strategy(self.save)
        with self.assertRaises(Conflict):
            self.case()
        self.assertEqual(self.service.store.list("case"), [])

    def test_saved_strategy_cannot_silently_drop_unsupported_conditions(self):
        self.analysis.store.mutate(self.run["id"], lambda s: s["result"].update(unsupported_conditions=["외국인 순매수"]))
        with self.assertRaises(Conflict):
            self.service.save_strategy(self.save)
        case = self.case()
        self.assertEqual(case["discovery"]["unsupported_conditions"], ["외국인 순매수"])

    def test_case_preserves_evidence_notes_are_append_only(self):
        case = self.case()
        original = copy.deepcopy(case["discovery"])
        first = {"expected_revision": 0, "reason": "사용자 생각", "assumptions": "수요 증가",
                 "invalidation": "수요 둔화", "watch_items": ["실적 확인"], "request_key": "note-000001"}
        case = self.service.save_note(case["id"], first)
        self.service.save_note(case["id"], first)
        second = {**first, "reason": "생각 수정", "expected_revision": 1, "request_key": "note-000002"}
        case = self.service.save_note(case["id"], second)
        self.assertEqual([n["reason"] for n in case["notes"]], ["사용자 생각", "생각 수정"])
        self.assertEqual(case["discovery"], original)
        with self.assertRaises(Conflict):
            self.service.save_note(case["id"], {**first, "request_key": "note-stale-1"})
        with self.assertRaises(ValueError):
            SaveNote.model_validate({**first, "watch_items": ["x" * 1001]})

    def test_recommendations_never_start_analysis_on_read(self):
        count = len(self.analysis.store.list())
        items = self.service.recommendations(self.run["id"], "000001")
        self.assertEqual(len(self.analysis.store.list()), count)
        self.assertEqual(items[-1]["source_run_id"], self.run["id"])
        self.assertIsNone(items[-1]["spec"]["as_of"])
        from pipeline.market_analysis.strategies import catalog
        available = {entry["id"] for entry in catalog() if entry["available"]}
        self.assertTrue(all(condition["strategy_id"] in available for item in items[:-1]
                            for condition in item["spec"]["strategy_conditions"]))
        with self.assertRaises(ValueError):
            self.service.recommendations(self.run["id"], "999999")

    def test_research_diff_records_changes_and_pins_note_revision(self):
        case = self.case()
        source = {"as_of": "2026-09-19", "warnings": ["자료 공백"], "lanes": [{"id": "market", "status": "partial",
                   "items": [{"id": "doc:1", "excerpt": "첫 근거"}]}]}
        self.service.packet_builder = lambda *args, **kwargs: copy.deepcopy(source)
        self.service.synthesizer = lambda *args, **kwargs: {"summary": "원문 기반 요약", "claims": [], "questions": [], "limitations": []}
        one = self.service.research(case["id"], {"question": "최초 조사", "as_of": None, "request_key": "research-001"})
        self.service._execute(one["id"])
        source["lanes"][0]["items"] = [{"id": "doc:1", "excerpt": "수정된 근거"}, {"id": "doc:2", "excerpt": "다음 근거"}]
        two = self.service.research(case["id"], {"question": "후속 조사", "as_of": None, "request_key": "research-002"})
        self.service._execute(two["id"])
        case = self.service.case(case["id"])
        second, first = case["research_runs"]
        self.assertEqual(first["packet"]["lanes"][0]["items"][0]["excerpt"], "첫 근거")
        self.assertEqual(second["status"], "partial")
        self.assertEqual(second["changes"]["changed_ids"], ["doc:1"])
        self.assertEqual(second["changes"]["added_ids"], ["doc:2"])
        self.assertEqual(second["changes"]["previous_run_id"], first["id"])

    def test_web_lane_records_collector_outcome_without_failing_research(self):
        from pipeline.market_analysis.discovery_preparation import pending_preparation
        case = self.case()
        self.service.preparer = lambda *args, **kwargs: {**pending_preparation(), "status": "completed"}
        self.service.packet_builder = lambda *args, **kwargs: {"as_of": "2026-09-19", "warnings": [], "lanes": [{"id": "web", "status": "partial", "items": [{"id": "doc:7", "excerpt": "웹 발췌"}]}]}
        self.service.synthesizer = lambda *args, **kwargs: {"summary": "요약", "claims": [], "questions": [], "limitations": []}
        calls = []
        def collector(code, name, sector, reason, *, cancel):
            calls.append((code, name, reason))
            return {"sources": [{"id": 1}, {"id": 2}], "overview": "고압 수소 어닐링 장비 회사"}, False
        self.service.web_collector = collector
        run = self.service.research(case["id"], {"question": "웹 포함 조사", "request_key": "research-web-1", "web": True})
        self.service._execute(run["id"])
        done = self.service.case(case["id"])["research_runs"][0]
        web = next(i for i in done["preparation"]["items"] if i["id"] == "web")
        self.assertEqual(web["status"], "collected", web)
        self.assertIn("출처 2건", web["detail"])
        self.assertEqual(calls[0][:2], ("000001", "테스트"))
        self.assertEqual(calls[0][2], "추세가 유지되는 기업", "the discovery question is passed as the research reason")
        self.assertEqual(done["status"], "partial")
        # Unchecked box → skipped, collector never called; collector failure → lane failed, research still completes.
        skipped = self.service.research(case["id"], {"question": "웹 제외", "request_key": "research-web-2", "web": False})
        self.service._execute(skipped["id"])
        self.assertEqual(next(i for i in self.service.case(case["id"])["research_runs"][0]["preparation"]["items"] if i["id"] == "web")["status"], "skipped")
        self.assertEqual(len(calls), 1)
        def broken(*args, **kwargs):
            raise RuntimeError("검색 도구 오류")
        self.service.web_collector = broken
        failed = self.service.research(case["id"], {"question": "웹 실패", "request_key": "research-web-3"})
        self.service._execute(failed["id"])
        latest = self.service.case(case["id"])["research_runs"][0]
        self.assertEqual(next(i for i in latest["preparation"]["items"] if i["id"] == "web")["status"], "failed")
        self.assertEqual(latest["status"], "partial", "web failure degrades the lane, not the research")

    def test_cancel_running_research_cannot_be_overwritten_by_completion(self):
        case = self.case()
        run = self.service.research(case["id"], {"question": "조사", "request_key": "research-001"})
        ready, release = threading.Event(), threading.Event()
        self.service.packet_builder = lambda *a, **k: {"lanes": [], "warnings": []}
        def synthesize(*args, **kwargs):
            ready.set()
            release.wait(3)
            self.assertTrue(kwargs["cancel"]())
            return {"summary": "취소 뒤 응답", "cost_usd": 0.1, "attempts": 1}
        self.service.synthesizer = synthesize
        worker = threading.Thread(target=self.service._execute, args=(run["id"],))
        worker.start()
        self.assertTrue(ready.wait(3))
        self.service.cancel(case["id"], run["id"])
        release.set()
        worker.join(3)
        result = self.service.store.get("research", run["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn("result", result)
        self.assertEqual(result["model_diagnostics"]["cost_usd"], 0.1)
        with self.assertRaises(FileNotFoundError):
            self.service.cancel("b" * 32, run["id"])

    def test_failure_retains_actual_packet_for_review(self):
        case = self.case()
        run = self.service.research(case["id"], {"question": "조사", "request_key": "research-001"})
        self.service.packet_builder = lambda *a, **k: {"lanes": [], "warnings": ["공백"]}
        def fail(*a, **k):
            raise RuntimeError("모델 응답 오류")
        self.service.synthesizer = fail
        self.service._execute(run["id"])
        result = self.service.store.get("research", run["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["packet"]["warnings"], ["공백"])
        self.assertNotIn("result", result)

    def test_worker_restart_marks_abandoned_research_interrupted(self):
        case = self.case()
        run = self.service.research(case["id"], {"question": "조사", "request_key": "research-001"})
        self.service.store.mutate("research", run["id"], lambda r: r.update(status="running"))
        restarted = DiscoveryService(self.analysis, self.root / "discovery", self.root / "missing-source.sqlite")
        restarted._stop.set()
        restarted._worker()
        self.assertEqual(restarted.store.get("research", run["id"])["status"], "interrupted")

    def test_api_rejects_forged_evidence_and_reports_conflicts(self):
        from routers import discovery
        previous = discovery._service
        discovery._service = self.service
        try:
            app = FastAPI()
            app.include_router(discovery.router, prefix="/api/analysis")
            client = TestClient(app)
            url = "/api/analysis/discovery"
            self.assertEqual(client.get(url + "/cases").json(), {"items": []})
            self.assertEqual(client.post(url + "/cases", json={"run_id": self.run["id"], "stock_code": "000001",
                "question": "조사", "request_key": "case-000001", "evidence": {"fake": True}}).status_code, 422)
            self.assertEqual(client.post(url + "/strategies", json=self.save).status_code, 200)
            self.assertEqual(client.post(url + "/strategies", json={**self.save, "name": "변경"}).status_code, 409)
            self.assertEqual(client.get(url + "/cases/" + "f" * 32).status_code, 404)
        finally:
            discovery._service = previous


if __name__ == "__main__":
    unittest.main()

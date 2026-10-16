"""Offline harness tests; actual sandbox code runs only against disposable DBs."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.market_analysis import AnalysisSpec, ModelAction, RunRequest
from pipeline.market_analysis.model import ClaudeModel, ModelError, ModelReply
from pipeline.market_analysis.runner import AnalysisService
from pipeline.market_analysis.store import Conflict, RunStore, StoreError, atomic_write, read_bytes, read_json


class FixtureModel:
    calls = 0
    ask = False
    ask_everything = False  # lists pattern-only fields although pattern='none' (2026-09-19 incident)
    corrupt = False
    no_execution = False
    exploratory = False  # first run_python saves an exploratory JSON, not the screen result (D-192 host finish must wait)

    def __init__(self, cwd):
        self.cwd = cwd

    def call(self, system, context, **kwargs):
        type(self).calls += 1
        if context["spec"] is None:
            spec = AnalysisSpec(pattern="none", require_52w=False, require_ma=self.ask,
                                min_market_cap=0, ma_period=2, hold_days=1).model_dump(mode="json")
            fields = ["window_scope", "price_basis", "include_same_day"] if self.ask_everything else (["price_basis"] if self.ask else [])
            action = {"action": "interpret", "spec": spec, "fields": fields}
        elif self.no_execution or (context["observations"] and not (self.exploratory and len(context["observations"]) == 1)):
            action = {"action": "finish", "result_path": "result.json",
                      "evidence_ids": [context["observations"][-1]["id"]] if context["observations"] else ["made-up"]}
        elif self.exploratory and not context["observations"]:
            action = {"action": "run_python", "code": "import json\nwith open('result.json','w') as f: json.dump({'peek': 1},f)\nprint('peek')\n"}
        else:
            code = (f"import sys,json\nsys.path.insert(0,{context['skill_dir']!r})\nimport analytics\n"
                    f"result=analytics.screen({context['data_dir']!r},{context['spec']!r})\n")
            if self.corrupt:
                code += "result['counts']['matched'] = 999\n"
            code += "with open('result.json','w') as f: json.dump(result,f,ensure_ascii=False)\nprint('screened')\n"
            action = {"action": "run_python", "code": code}
        return ModelReply(ModelAction.model_validate(action), .01)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.sqlite"
        connection = sqlite3.connect(self.source)
        connection.executescript("""
            CREATE TABLE stock_prices(stock_code TEXT,trade_date TEXT,open REAL,high REAL,
                low REAL,close REAL,volume REAL,market_cap REAL,shares REAL);
            CREATE TABLE companies(stock_code TEXT,corp_name TEXT,market TEXT);
            INSERT INTO companies VALUES('000001','테스트','KOSPI');
            INSERT INTO stock_prices VALUES('000001','2025-01-02',100,105,95,101,10,600000000000,100);
            INSERT INTO stock_prices VALUES('000001','2025-01-03',102,106,101,105,10,600000000000,100);
        """)
        connection.commit()
        connection.close()
        self.before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        FixtureModel.calls = 0
        FixtureModel.ask = FixtureModel.corrupt = FixtureModel.no_execution = FixtureModel.ask_everything = FixtureModel.exploratory = False
        self.service = AnalysisService(self.root / "state", source_db=self.source,
                                       model_factory=FixtureModel, preflight=lambda: {})
        # Drive deterministically without an asynchronous worker in most tests.
        self.service.start = lambda: None

    def tearDown(self):
        self.service.stop()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.before)
        self.temp.cleanup()

    def create(self, key="fixture-request-0001"):
        return self.service.create(RunRequest(question="시총 조건만 조회", request_key=key).model_dump(mode="json"))

    def test_complete_real_sandbox_and_independent_verification(self):
        run = self.create()
        self.service.process(run["id"])
        result = self.service.store.read(run["id"])
        self.assertEqual(result["status"], "partial", result.get("error"))
        self.assertEqual(result["result"]["counts"]["matched"], 1)
        self.assertEqual(result["result"]["verification"]["status"], "matched")
        self.assertEqual(result["result"]["items"][0]["status"], "provisional")
        self.assertEqual(result["steps"], 1)
        # D-192: 완성된 result.json을 본 호스트가 finish를 합성하므로 모델은 해석·코드 2콜만 한다.
        self.assertEqual(FixtureModel.calls, 2)
        self.assertAlmostEqual(result["cost_usd"], .02)
        self.assertEqual(result["_history"][-1], {"role": "host", "finish": result["result"]["verification"]["evidence_ids"][0]})
        self.assertEqual({a["kind"] for a in result["artifacts"]}, {"json", "csv"})
        chart = self.service.chart(run["id"], "000001")
        self.assertEqual(len(chart["prices"]), 2)
        events = self.service.store.events(run["id"])
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(any(e["type"] == "STEP_STARTED" for e in events))
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        self.assertFalse(events[-1]["result"]["task_complete"])

    def test_idempotency_and_no_duplicate_runs(self):
        first, second = self.create(), self.create()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.service.store.list()), 1)
        with self.assertRaises(Conflict):
            self.service.create({"question": "다른 질문", "request_key": "fixture-request-0001", "as_of": None})

    def test_a2ui_resume_checks_interrupt_and_requested_fields(self):
        FixtureModel.ask = True
        run = self.create()
        self.service.process(run["id"])
        paused = self.service.store.read(run["id"])
        self.assertEqual(paused["status"], "waiting_input", paused["error"])
        self.assertEqual(paused["pending"]["fields"], ["price_basis"])
        with self.assertRaises(Conflict):
            self.service.resume(run["id"], "wrong", {"price_basis": "low"})
        with self.assertRaises(ValueError):
            self.service.resume(run["id"], paused["pending"]["id"], {"price_basis": "low", "network": True})
        payload = {"userAction": {"name": "resume_analysis", "surfaceId": paused["pending"]["surfaceId"],
                                  "context": {"price_basis": ["low"]}}}
        self.service.resume(run["id"], paused["pending"]["id"], payload)
        with self.assertRaises(Conflict):
            self.service.resume(run["id"], paused["pending"]["id"], payload)
        self.service.process(run["id"])
        final = self.service.store.read(run["id"])
        self.assertEqual(final["spec"]["price_basis"], "low")
        self.assertEqual(final["status"], "partial", final["error"])
        self.assertEqual(FixtureModel.calls, 2)  # 해석·코드. finish는 호스트 합성(D-192)

    def test_inapplicable_ask_fields_are_skipped_instead_of_failing(self):
        # pattern='none' and require_ma=False: none of the listed fields apply, so the search must just proceed.
        FixtureModel.ask_everything = True
        run = self.create()
        self.service.process(run["id"])
        final = self.service.store.read(run["id"])
        self.assertEqual(final["status"], "partial", final["error"])
        self.assertIsNone(final["pending"])
        notes = [e["value"]["text"] for e in self.service.store.events(run["id"]) if e.get("name") == "analysis.plan" and "확인하지 않고" in e["value"]["text"]]
        self.assertTrue(notes and "window_scope" in notes[0] and "include_same_day" in notes[0], notes)
        # With MA requested only price_basis survives the filter and is actually asked.
        FixtureModel.ask = True
        second = self.create("fixture-request-0002")
        self.service.process(second["id"])
        paused = self.service.store.read(second["id"])
        self.assertEqual(paused["status"], "waiting_input", paused["error"])
        self.assertEqual(paused["pending"]["fields"], ["price_basis"])

    def test_default_within_days_reaches_the_model_context(self):
        seen = []
        class Capturing(FixtureModel):
            def call(self, system, context, **kwargs):
                seen.append(context.get("default_within_days"))
                return super().call(system, context, **kwargs)
        self.service.model_factory = Capturing
        run = self.service.create(RunRequest(question="시총 조건만 조회", request_key="fixture-request-0003", default_within_days=5).model_dump(mode="json"))
        self.service.process(run["id"])
        self.assertEqual(seen[0], 5)
        self.assertEqual(self.service.store.read(run["id"])["status"], "partial")
        with self.assertRaises(ValueError):
            RunRequest(question="x", request_key="fixture-request-0004", default_within_days=0)

    def test_cancel_before_work_does_not_call_model(self):
        run = self.create()
        self.service.cancel(run["id"])
        self.service.process(run["id"])
        self.assertEqual(FixtureModel.calls, 0)
        self.assertEqual(self.service.store.read(run["id"])["status"], "cancelled")

    def test_host_finish_waits_for_a_complete_screen_result(self):
        FixtureModel.exploratory = True
        run = self.create()
        self.service.process(run["id"])
        result = self.service.store.read(run["id"])
        self.assertEqual(result["status"], "partial", result.get("error"))
        self.assertEqual(result["result"]["verification"]["status"], "matched")
        self.assertEqual(result["steps"], 2)  # 탐색 저장 → 호스트가 끝내지 않음 → 진짜 계산 → 호스트 finish
        self.assertEqual(FixtureModel.calls, 3)
        self.assertEqual(result["result"]["verification"]["evidence_ids"], [result["_observations"][1]["id"]])

    def test_unchanged_source_reuses_snapshot_and_changed_source_exports_fresh(self):
        first = self.create("snapshot-reuse-1")
        self.service.process(first["id"])
        second = self.create("snapshot-reuse-2")
        self.service.process(second["id"])
        a, b = self.service.store.read(first["id"]), self.service.store.read(second["id"])
        self.assertEqual(b["status"], "partial", b.get("error"))
        self.assertEqual(a["_snapshot_id"], b["_snapshot_id"])  # D-193: 원본 지문 동일 → 같은 스냅샷
        self.assertEqual(a["_snapshot_hashes"], b["_snapshot_hashes"])
        self.assertTrue(b["snapshot"]["reused"])
        self.assertNotIn("reused", a["snapshot"])
        self.assertEqual(b["result"]["counts"], a["result"]["counts"])
        directories = [d for d in (self.service.store.root / "snapshots").iterdir() if d.is_dir()]
        self.assertEqual(len(directories), 1)
        # 원본이 바뀌면(시세 한 행 추가) 지문이 달라져 새로 내보낸다.
        connection = sqlite3.connect(self.source)
        connection.execute("INSERT INTO stock_prices VALUES('000001','2025-01-06',105,110,104,108,12,650000000000,100)")
        connection.commit(); connection.close()
        self.before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        third = self.create("snapshot-reuse-3")
        self.service.process(third["id"])
        c = self.service.store.read(third["id"])
        self.assertEqual(c["status"], "partial", c.get("error"))
        self.assertNotEqual(c["_snapshot_id"], a["_snapshot_id"])
        self.assertEqual(c["snapshot"]["as_of"], "2025-01-06")
        # 등록된 스냅샷이 디스크에서 변조되면 차단이 아니라 새로 내보낸다.
        parquet = self.service.store.root / "snapshots" / c["_snapshot_id"] / "daily.parquet"
        parquet.chmod(0o600); parquet.write_bytes(b"modified")
        fourth = self.create("snapshot-reuse-4")
        self.service.process(fourth["id"])
        d = self.service.store.read(fourth["id"])
        self.assertEqual(d["status"], "partial", d.get("error"))
        self.assertNotIn(d["_snapshot_id"], {a["_snapshot_id"], c["_snapshot_id"]})

    def test_identical_inputs_reuse_verified_result_without_recomputing(self):
        first = self.create("cache-first-run")
        self.service.process(first["id"])
        a = self.service.store.read(first["id"])
        self.assertEqual(a["status"], "partial", a.get("error"))
        FixtureModel.calls = 0
        second = self.create("cache-second-run")
        self.service.process(second["id"])
        b = self.service.store.read(second["id"])
        self.assertEqual(b["status"], "partial", b.get("error"))
        # D-194: 같은 스냅샷·spec·스킬 → 검증된 결과 재사용. 코드 콜·계산·재계산 없음(해석 콜만).
        self.assertEqual(FixtureModel.calls, 1)
        self.assertEqual(b["steps"], 0)
        self.assertEqual(b["result"]["verification"]["cached_from"], first["id"])
        self.assertEqual(b["result"]["verification"]["status"], "matched")
        self.assertEqual(b["result"]["items"], a["result"]["items"])
        self.assertEqual(b["result"]["counts"], a["result"]["counts"])
        self.assertEqual({x["kind"] for x in b["artifacts"]}, {"json", "csv"})
        self.assertEqual(b["_history"][-1], {"role": "host", "cached_result": first["id"]})
        self.assertEqual(len(self.service.chart(second["id"], "000001")["prices"]), 2)
        # spec이 다르면(선택 실행, 시총 하한 변경) 캐시를 쓰지 않는다.
        spec = {**a["spec"], "min_market_cap": 1}
        spec.pop("price_adjustment", None)
        third = self.service.create(RunRequest(question="선택 실행", request_key="cache-third-run", spec=spec).model_dump(mode="json"))
        self.service.process(third["id"])
        c = self.service.store.read(third["id"])
        self.assertEqual(c["status"], "partial", c.get("error"))
        self.assertNotIn("cached_from", c["result"]["verification"])
        self.assertEqual(c["steps"], 1)

    def test_finish_without_execution_is_rejected(self):
        FixtureModel.no_execution = True
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertNotEqual(state["status"], "completed")
        self.assertIsNone(state["result"])
        self.assertEqual(state["steps"], 0)

    def test_mismatching_result_never_becomes_verified(self):
        FixtureModel.corrupt = True
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertEqual(state["status"], "partial")
        self.assertIsNone(state["result"])
        self.assertIn("반복", state["error"])
        self.assertEqual(state["artifacts"], [])

    def test_recovery_keeps_input_and_budget_and_detects_snapshot_tamper(self):
        run = self.create()
        self.service.process(run["id"])
        before = self.service.store.read(run["id"])
        self.service._update(run["id"], status="running", result=None)
        self.service.recover()
        paused = self.service.store.read(run["id"])
        self.assertEqual(paused["status"], "interrupted")
        self.assertEqual(paused["_snapshot_id"], before["_snapshot_id"])
        self.assertEqual(paused["cost_usd"], before["cost_usd"])
        self.service.resume(run["id"], paused["pending"]["id"], {})
        snapshot = self.service.store.root / "snapshots" / paused["_snapshot_id"] / "daily.parquet"
        snapshot.chmod(0o600)
        snapshot.write_bytes(b"modified")
        self.service.process(run["id"])
        self.assertEqual(self.service.store.read(run["id"])["status"], "blocked")
        self.assertEqual(FixtureModel.calls, 2)  # 스냅샷 변조는 호스트 finish의 해시 검증에서 차단

    def test_file_reads_reject_links_traversal_and_oversize(self):
        work = self.root / "work"
        work.mkdir()
        (work / "data.json").write_text('{"safe":true}')
        (work / "link.json").symlink_to(self.source)
        os.link(self.source, work / "hard.json")
        for path in ("link.json", "hard.json", "../source.sqlite", str(self.source)):
            with self.assertRaises((OSError, StoreError)):
                read_bytes(work, path)
        with self.assertRaises(StoreError):
            read_bytes(work, "data.json", 2)
        (work / "nan.json").write_text('{"value":NaN}')
        with self.assertRaises(StoreError):
            read_json(work, "nan.json")

    def test_csv_artifact_sanitizes_formula_cells_and_rejects_symlink(self):
        run = self.create()
        work = self.root / "work"
        work.mkdir()
        (work / "out.csv").write_text('name,value\n=1+1,123\n@evil,42\n')
        item = self.service.store.register_artifact(run["id"], work, "out.csv")
        _, data = self.service.store.artifact(run["id"], item["id"])
        self.assertIn("'=1+1", data.decode("utf-8-sig"))
        self.assertIn("'@evil", data.decode("utf-8-sig"))
        (work / "bad.json").symlink_to(self.source)
        with self.assertRaises(OSError):
            self.service.store.register_artifact(run["id"], work, "bad.json")

    def test_model_command_disables_tools_hooks_plugins_and_mcp(self):
        model = ClaudeModel(self.root / "model", executable="/fixture/claude")
        command = model.command("test", .1)
        for flag in ("--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        self.assertEqual(json.loads(command[command.index("--mcp-config") + 1]), {"mcpServers": {}})
        self.assertTrue(json.loads(command[command.index("--settings") + 1])["disableAllHooks"])

    def test_call_budget_stops_without_fabricating_completion(self):
        self.service.max_calls = 1
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertEqual(FixtureModel.calls, 1)
        self.assertEqual(state["status"], "failed")
        self.assertIsNone(state["result"])
        self.assertAlmostEqual(state["cost_usd"], .01)

    def test_unknown_model_cost_is_explicit_and_prevents_retry(self):
        class UnknownCost:
            def __init__(self, cwd):
                pass

            def call(self, *args, **kwargs):
                raise ModelError("timeout; cost unknown")
        self.service.model_factory = UnknownCost
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertTrue(state["cost_uncertain"])
        self.assertEqual(state["cost_usd"], 0)
        self.assertEqual(state["_calls"], 1)
        self.service._update(run["id"], status="running")
        self.service.recover()
        state = self.service.store.read(run["id"])
        self.service.resume(run["id"], state["pending"]["id"], {})
        self.service.process(run["id"])
        self.assertEqual(self.service.store.read(run["id"])["_calls"], 1)

    def test_source_adjustment_cannot_be_upgraded_by_model(self):
        class ForgedAdjustment(FixtureModel):
            def call(self, *args, **kwargs):
                reply = super().call(*args, **kwargs)
                if reply.action.spec:
                    reply.action.spec.price_adjustment = "adjusted"
                return reply
        self.service.model_factory = ForgedAdjustment
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertEqual(state["spec"]["price_adjustment"], "unknown")
        self.assertEqual(state["result"]["items"][0]["status"], "provisional")

    def test_model_and_runtime_cancellation_prevents_next_action(self):
        owner = self.service

        class CancelDuringCode:
            def __init__(self, **kwargs):
                pass

            def run(self, *args, **kwargs):
                from pipeline.market_analysis.runtime import Result
                owner.cancel(owner.store.list()[0]["id"])
                return Result(-9, "", "", cancelled=True)
        self.service.sandbox_factory = CancelDuringCode
        run = self.create()
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertEqual(state["status"], "cancelled")
        self.assertIsNone(state["result"])
        self.assertEqual(FixtureModel.calls, 2)

    def test_api_replay_only_and_strict_request_schema(self):
        from routers import analysis
        app = FastAPI()
        app.include_router(analysis.router)
        with patch.object(analysis, "_service", self.service):
            client = TestClient(app)
            response = client.post("/api/analysis/runs", json={"question": "시총 조회", "request_key": "api-request-0001"})
            self.assertEqual(response.status_code, 200)
            run_id = response.json()["id"]
            client.post(f"/api/analysis/runs/{run_id}/cancel")
            first = client.get(f"/api/analysis/runs/{run_id}/events").text
            self.assertIn("analysis.state", first)
            after = self.service.store.events(run_id)[-1]["seq"]
            replay = client.get(f"/api/analysis/runs/{run_id}/events?after={after}").text
            self.assertEqual(replay, "")
            self.assertEqual(FixtureModel.calls, 0)
            bad = client.post("/api/analysis/runs", json={"question": "hi", "request_key": "api-request-0002", "dataDir": "/"})
            self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()

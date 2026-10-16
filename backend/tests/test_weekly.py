import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.weekly import Claim, Figure, Report, ResumeRequest, RunRequest
from pipeline.weekly.calculations import compare, metrics, outcomes, select_analogues
from pipeline.weekly.evidence import Evidence, instant, make_item, observation_bound, publication_bound
from pipeline.weekly.review import check
from pipeline.weekly.runner import Runner
from pipeline.weekly.sources import safe_url
from pipeline.weekly.store import Store, dumps
from pipeline.weekly.tools import Fetch, Toolset
from pipeline.weekly.worker import Cancelled, isolated
from routers import experiment_weekly

UTC = timezone.utc


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.source = root / "source.sqlite"
        self.store = Store(root / "weekly.sqlite", root / "runs", self.source)
        self.cutoff = datetime.now(UTC) - timedelta(seconds=2)
        self.start = (self.cutoff - timedelta(days=95)).date().isoformat()
        self.end = (self.cutoff - timedelta(days=5)).date().isoformat()
        self.quote = "매출이 늘었지만 현금흐름 전환은 아직 확인되지 않았다."
        with closing(sqlite3.connect(self.source)) as c, c:
            c.executescript("""
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,source_id TEXT,title TEXT,url TEXT,published_at TEXT,fetched_at TEXT,raw_content TEXT,markdown TEXT,content_hash TEXT,media_json TEXT,digest_status TEXT);
            CREATE TABLE transcripts(raw_doc_id INTEGER,call_date TEXT);
            CREATE TABLE youtube_digest_jobs(doc_id INTEGER,transcript TEXT);
            CREATE TABLE market_indicators(snapshot_date TEXT,indicator TEXT,value REAL,extra_json TEXT,fetched_at TEXT);
            CREATE TABLE us_prices(stock_code TEXT,trade_date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,fetched_at TEXT);
            """)
            pub = (self.cutoff - timedelta(days=3)).isoformat()
            fetched = (self.cutoff - timedelta(days=2)).isoformat()
            rows = [
                (1, "blog", "one", "시장 변화", "https://example.com/1", pub, fetched, self.quote, "short", "h1", "[]", None),
                (2, "telegram", "copy", "시장 변화 재전파", "https://example.com/2", pub, fetched, self.quote, self.quote, "h2", "[]", None),
                (3, "blog", "future", "시장 변화 미래", None, (self.cutoff + timedelta(days=1)).isoformat(), fetched, "미래정보", "", "h3", "[]", None),
                (4, "blog", "late", "시장 변화 늦은 수집", None, pub, (self.cutoff + timedelta(days=1)).isoformat(), "후대 수집", "", "h4", "[]", None),
                (5, "transcript", "bad", "미래 분기 날짜", None, pub, fetched, "미래 컨콜", "", "h5", "[]", None),
                (6, "youtube", "derived", "생성 정리", None, pub, fetched, "AI가 생성한 정리본", "AI 정리본", "h6", "[]", "ok"),
                (7, "blog", "long", "긴 문서", None, pub, fetched, "가" * 18000 + "중요한 반대 증거", "요약", "h7", "[]", None),
            ]
            c.executemany("INSERT INTO raw_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.execute("INSERT INTO transcripts VALUES(?,?)", (5, (self.cutoff + timedelta(days=100)).date().isoformat()))
            for i in range(100):
                day = (self.cutoff - timedelta(days=105 - i)).date().isoformat()
                value = 100 + i * 0.5 + (i % 7)
                c.execute("INSERT INTO us_prices VALUES(?,?,?,?,?,?,?,?)", ("SPY", day, value, value, value, value, 1000 + i, fetched))

    def request(self, **kwargs):
        return RunRequest(request_key=kwargs.pop("request_key", "test"), cutoff=self.cutoff,
                          allow_network=False, **kwargs)

    def prepare(self, **kwargs):
        req = self.request(**kwargs)
        rid, _ = self.store.create(req)
        run = self.store.get(rid)
        ev = Evidence(self.store.directory(rid))
        coverage = ev.freeze(self.source, run["config"])
        cp = run["checkpoint"]
        cp["coverage"], cp["corpus_sha256"] = coverage, ev.file_hash()
        self.store.save(rid, checkpoint=cp)
        return rid, ev, cp, run["config"]

    def fake_model(self, phase, payload):
        data = json.loads(payload["prompt"])
        context = data.get("context", {})
        catalog = context.get("read_evidence_catalog", [])
        calc = next((x["id"] for x in catalog if x["kind"] == "calculation"), None)
        if phase == "analyst":
            n = 24 - context["budget"]["steps_left"]
            actions = [
                ("read_evidence", {"evidence_id": "d1"}),
                ("compare_windows", {"evidence_id": "s-us-SPY", "windows": [{"start": self.start, "end": self.end, "rationale": "최근 가격과 현금흐름의 차이를 확인"}]}),
                ("record_decision", {"hypothesis": self.hypothesis(calc), "reason": "가격과 사업 실행을 구분해야 함", "alternatives_considered": ["실행 이익이 가격을 설명할 수 있음"], "next_investigation": "현금흐름 확인"}),
                ("render_chart", {"evidence_id": "s-us-SPY", "start": self.start, "end": self.end}),
                ("finish_research", {"reason": "관측·대안·반증 조건을 확인"}),
            ]
            tool, args = actions[min(n - 1, len(actions) - 1)]
            output = {"tool": tool, "args": args, "question": "가격 상승을 이익 실현이 뒷받침하는가", "reason": "실행과 기대를 구분"}
        elif phase in {"write", "revise"}:
            output = self.report(calc).model_dump()
        else:
            output = {"issues": [], "assessment": "주어진 근거의 범위에 한정한 조건부 진단"}
        return {"text": dumps(output), "model": "fake", "engine": "test", "usage": {"input": 1, "output": 1}}

    def hypothesis(self, calc=None):
        return {"id": "cash", "question": "현금흐름이 기대를 확인하는가", "judgment": "현금흐름 확인 전에는 조건부로 유지", "alternative": "이익 실현이 주가를 설명할 가능성", "change_condition": "현금흐름이 매출 증가를 뒷받침하면 판단을 상향", "evidence_ids": ["d1"] + ([calc] if calc else [])}

    def report(self, calc):
        return Report.model_validate({"title": "가격과 사업 실행 사이의 간극",
            "standfirst": {"id": "c1", "kind": "interpretation", "text": "가격의 강세와 사업 현금화는 구분해서 볼 필요가 있다.", "supports": [{"evidence_id": "d1", "quote": self.quote}]},
            "sections": [{"heading": "관측과 대안", "claims": [
                {"id": "c2", "kind": "fact", "text": "선택 구간의 가격 수익률은 {{n1}}다.", "figures": [{"id": "n1", "evidence_id": calc, "path": "/windows/0/metrics/return_pct", "decimals": 2}]},
                {"id": "c3", "kind": "fact", "text": "해당 글은 매출 증가에도 현금흐름 전환이 확인되지 않았다고 서술한다.", "supports": [{"evidence_id": "d1", "quote": self.quote}]},
            ]}], "hypotheses": [self.hypothesis(calc)], "gaps": []})

    def test_cutoff_before_ranking_deduplicates_and_freezes_raw(self):
        rid, ev, cp, cfg = self.prepare()
        found = ev.find("시장 변화", limit=20)
        self.assertEqual(found["total_unique_texts"], 1)
        for eid in ("d3", "d4", "d5"):
            with self.assertRaises(KeyError):
                ev.get(eid)
        self.assertEqual(ev.get("d1")["text"], self.quote)
        before = ev.file_hash()
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute("UPDATE raw_documents SET raw_content='changed' WHERE id=1")
        self.assertEqual(ev.get("d1")["text"], self.quote)
        self.assertEqual(ev.file_hash(), before)

    def test_read_beyond_prefix_and_quote_gate(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        page = tools.dispatch("read_evidence", {"evidence_id": "d7", "start": 18000, "length": 100})
        self.assertEqual(page["text"], "중요한 반대 증거")
        self.assertIn("d7", cp["read_ids"])
        with self.assertRaises(ValueError):
            tools.dispatch("read_evidence", {"evidence_id": "../../source"})

    def test_definition_and_start_shift(self):
        points = [{"date": f"2026-01-{i+1:02d}", "value": v} for i, v in enumerate([100, 120, 90, 110])]
        m = metrics(points)
        self.assertAlmostEqual(m["return_pct"], 10)
        self.assertAlmostEqual(m["drawdown_pct"], -25)
        self.assertNotIn("return_pct", metrics(points, metric_kind="yield"))
        item = make_item("s", "series", {"metric_kind": "price"}, {"points": points})
        comp = compare(item, [{"start": "2026-01-02", "end": "2026-01-04", "rationale": "event"}], [-1, 1])
        self.assertLess(comp["windows"][0]["metrics"]["return_pct"], 0)
        self.assertGreater(comp["windows"][0]["sensitivity"][0]["metrics"]["return_pct"], 0)

    def test_analogue_population_frozen_before_outcomes(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        points = ev.get("s-us-SPY")["data"]["points"]
        selected = tools.dispatch("find_analogues", {"evidence_id": "s-us-SPY", "target_start": points[-20]["date"], "target_end": points[-1]["date"], "rationale": "형태의 차이를 비교"})
        fixed = ev.get(selected["id"])
        before = dumps(fixed)
        result = tools.dispatch("evaluate_outcomes", {"selection_id": selected["id"], "horizon": 10})
        self.assertEqual(before, dumps(ev.get(selected["id"])))
        self.assertTrue(ev.get(result["id"])["data"]["outcomes"])
        self.assertTrue(all(c["end"] < points[-20]["date"] for c in fixed["data"]["candidates"]))
        with self.assertRaises(ValueError):
            tools.dispatch("evaluate_outcomes", {"selection_id": "invented"})

    def test_live_and_historical_date_boundaries(self):
        bound, precision = publication_bound("2026-01-01")
        self.assertEqual(bound, datetime(2026, 1, 2, 12, tzinfo=UTC))
        self.assertIsNone(instant("2026-01-01T12:00:00"))
        self.assertEqual(observation_bound("2026-07-01", "us:SPY").hour, 20)
        self.assertEqual(observation_bound("2026-01-02", "us:SPY").hour, 21)
        rid, ev, cp, cfg = self.prepare(mode="public_reconstruction")
        self.assertEqual(ev.get("d4")["meta"]["temporal_status"], "historical_version_unverified")
        self.assertEqual(ev.find("후대")["total_unique_texts"], 0)
        with self.assertRaises(ValueError):
            Toolset(self.store, rid, cp, cfg).dispatch("read_evidence", {"evidence_id": "d4"})

    def test_source_allowlist_and_missing_args(self):
        with self.assertRaises(ValueError):
            safe_url("https://127.0.0.1/private")
        with self.assertRaises(ValueError):
            safe_url("https://federalreserve.gov.evil.example/a")
        with self.assertRaises(ValueError):
            Fetch(provider="yahoo_prices", ticker="0700.HK", purpose="check", start="2026-01-01", end="2026-02-01")
        with self.assertRaises(ValueError):
            Fetch(provider="fred", series="UNKNOWN", purpose="check", start="2026-01-01", end="2026-02-01")

    def test_idempotency_and_operating_db_guard(self):
        req = self.request()
        rid, created = self.store.create(req)
        self.assertTrue(created)
        self.assertEqual(self.store.create(req), (rid, False))
        with patch("pipeline.weekly.store.now", return_value=(self.cutoff + timedelta(minutes=10)).isoformat()):
            retry = RunRequest.model_validate(req.model_dump())
            self.assertEqual(self.store.create(retry), (rid, False))
            with self.assertRaisesRegex(ValueError, "과거 cutoff"):
                self.store.create(retry.model_copy(update={"request_key": "new-stale-cutoff"}))
        with self.assertRaises(ValueError):
            self.store.create(self.request(scope="different"))
        changed = req.model_copy(update={"cutoff": self.cutoff - timedelta(seconds=1)})
        with self.assertRaises(ValueError):
            self.store.create(changed)
        with self.assertRaises(ValueError):
            Store(self.source, source_path=self.source)

    def test_complete_execution_has_real_tools_reviews_artifacts_no_source_writes(self):
        rid, _ = self.store.create(self.request())
        source_before = self.source.read_bytes()
        run = Runner(self.store, self.fake_model).execute(rid)
        self.assertEqual(run["status"], "complete", run["checkpoint"].get("final_review", run["error"]))
        self.assertEqual(source_before, self.source.read_bytes())
        self.assertEqual(run["checkpoint"]["steps"], 5)
        self.assertTrue(run["checkpoint"]["decisions"])
        html = (self.store.directory(rid) / "briefing.html").read_text()
        self.assertIn("고정 근거", html)
        self.assertNotIn("{{n1}}", html)
        self.assertTrue((self.store.directory(rid) / "events.json").exists())

    def test_reviewer_block_cannot_be_complete(self):
        def blocked(phase, payload):
            if phase == "review":
                return {"text": dumps({"issues": [{"claim_id": "c1", "severity": "blocking", "code": "causal_overreach", "reason": "경쟁 설명 확인이 부족"}], "assessment": "수정 필요"})}
            return self.fake_model(phase, payload)
        rid, _ = self.store.create(self.request(review_rounds=1))
        run = Runner(self.store, blocked).execute(rid)
        self.assertEqual(run["status"], "partial")

    def test_unread_quote_and_fabricated_figure_blocked(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        tools.dispatch("read_evidence", {"evidence_id": "d1"})
        result = tools.dispatch("compare_windows", {"evidence_id": "s-us-SPY", "windows": [{"start": self.start, "end": self.end, "rationale": "test"}]})
        report = self.report(result["id"])
        report.sections[0].claims[1].supports[0].quote = "원문에는 없는 문장"
        report.sections[0].claims[0].figures[0].path = "/windows/100/metrics/return_pct"
        codes = {i["code"] for i in check(report, ev, cp)}
        self.assertIn("quote_not_read", codes)
        self.assertIn("invalid_figure", codes)

    def test_cancel_and_resume_preserve_snapshot(self):
        rid, ev, cp, cfg = self.prepare()
        self.store.cancel(rid)
        called = []
        run = Runner(self.store, lambda *a: called.append(a)).execute(rid)
        self.assertEqual(run["status"], "cancelled")
        self.assertFalse(called)
        before = ev.file_hash()
        self.store.resume(rid, ResumeRequest())
        self.assertEqual(self.store.create(self.request()), (rid, False))
        resumed = self.store.get(rid)
        self.assertEqual(before, ev.file_hash())
        tools = Toolset(self.store, rid, resumed["checkpoint"], {**cfg, "allow_network": True})
        with self.assertRaises(ValueError):
            tools.dispatch("fetch_source", {"provider": "official_page", "url": "https://www.federalreserve.gov/", "purpose": "test"})

    def test_snapshot_tamper_stops_resume(self):
        rid, ev, cp, cfg = self.prepare()
        with closing(sqlite3.connect(ev.path)) as c, c:
            c.execute("UPDATE items SET text='tampered' WHERE id='d1'")
        run = Runner(self.store, self.fake_model).execute(rid)
        self.assertEqual(run["status"], "failed")
        self.assertIn("hash", run["error"])

    def test_gets_do_not_initialize_or_generate_and_artifact_traversal(self):
        app = FastAPI()
        app.include_router(experiment_weekly.router)
        with patch.object(experiment_weekly, "Store", return_value=self.store), TestClient(app) as client:
            self.assertEqual(client.get("/api/experiments/weekly/runs").json(), [])
            self.assertFalse(self.store.db_path.exists())
            rid, _, _, _ = self.prepare()
            response = client.get(f"/api/experiments/weekly/runs/{rid}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "queued")
            self.assertEqual(client.get(f"/api/experiments/weekly/runs/{rid}/artifacts/corpus.sqlite").status_code, 404)

    def test_worker_cancellation(self):
        with self.assertRaises(Cancelled):
            isolated("model", {}, timeout=1, cancelled=lambda: True)

    def test_system_replay_uses_prior_snapshot_only(self):
        rid, ev, cp, cfg = self.prepare()
        replay_request = RunRequest(request_key="replay", mode="system_replay", replay_run_id=rid, allow_network=False)
        replay_id, _ = self.store.create(replay_request)
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute("UPDATE raw_documents SET raw_content='future mutation' WHERE id=1")
        replay = Evidence(self.store.directory(replay_id))
        replay.freeze(self.source, self.store.get(replay_id)["config"], replay_directory=self.store.directory(rid))
        self.assertEqual(replay.get("d1")["text"], self.quote)
        self.assertEqual(ev.file_hash(), replay.file_hash())
        self.assertTrue((replay.directory / "snapshot.json").exists())

    def test_model_output_repair_and_tool_failure_are_bounded(self):
        writes = []
        def invalid_once(phase, payload):
            if phase == "write":
                writes.append(1)
                if len(writes) == 1:
                    return {"text": "not JSON"}
            return self.fake_model(phase, payload)
        rid, _ = self.store.create(self.request())
        run = Runner(self.store, invalid_once).execute(rid)
        self.assertEqual(run["status"], "complete", run["error"])
        self.assertEqual(len(writes), 2)
        self.assertTrue(any(e["kind"] == "output_validation_error" for e in self.store.events(rid)))

    def test_memory_does_not_include_later_finished_analysis(self):
        rid, _ = self.store.create(self.request())
        cp = self.store.get(rid)["checkpoint"]
        cp["draft"] = {"hypotheses": [self.hypothesis()]}
        self.store.save(rid, checkpoint=cp, status="complete")
        self.assertEqual(self.store.memory(self.cutoff.isoformat(), "other"), [])
        self.assertEqual(len(self.store.memory(datetime.now(UTC).isoformat(), "other")), 1)

    def test_worker_recovery_requires_absent_owner(self):
        import fcntl
        rid, ev, cp, cfg = self.prepare()
        self.store.save(rid, status="researching")
        with self.store.db_path.with_suffix(".worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ValueError):
                self.store.recover(rid)
            duplicate = Runner(self.store, self.fake_model).execute(rid)
            self.assertEqual(duplicate["status"], "researching")
        self.assertEqual(self.store.recover(rid)["status"], "failed")
        self.store.resume(rid, ResumeRequest())
        self.assertEqual(self.store.get(rid)["status"], "queued")

    def test_public_reconstruction_does_not_promote_generated_summary(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        tools.dispatch("read_evidence", {"evidence_id": "d6"})
        tools.dispatch("read_evidence", {"evidence_id": "d1"})
        result = tools.dispatch("compare_windows", {"evidence_id": "s-us-SPY", "windows": [{"start": self.start, "end": self.end, "rationale": "test"}]})
        report = self.report(result["id"])
        support = report.sections[0].claims[1].supports[0]
        support.evidence_id, support.quote = "d6", ev.get("d6")["text"]
        self.assertIn("derived_as_fact", {i["code"] for i in check(report, ev, cp)})

    def test_expert_evaluation_keeps_scores_empty_and_same_input_baseline(self):
        from pipeline.weekly.evaluation import build_packet
        rid, _ = self.store.create(self.request())
        run = Runner(self.store, self.fake_model).execute(rid)
        def baseline(payload):
            given = json.loads(payload["prompt"])
            self.assertNotIn("decisions", given)
            self.assertNotIn("report", given)
            self.assertNotIn("REFERENCE_ONLY_SENTINEL", payload["prompt"])
            calc = next(x["id"] for x in given["evidence"] if x["kind"] == "calculation")
            return {"text": self.report(calc).model_dump_json()}
        reference = self.store.directory(rid) / "reference-manifest.json"
        reference.write_text(json.dumps({"url": "https://example.com/weekly", "title": "REFERENCE_ONLY_SENTINEL", "images": [{"file": "chart.png"}]}))
        path = Path(build_packet(self.store, rid, baseline=True, model_call=baseline, reference_manifest=reference))
        score = json.loads((path.parent / "expert-scorecard.json").read_text())
        self.assertTrue(all(s["expert_pass"] is None for s in score["reports"].values()))
        self.assertEqual(score["reference_weekly_path"], str(reference))
        manifest = json.loads((path.parent / "manifest.json").read_text())
        self.assertIn("single_pass", manifest["variants"])
        self.assertEqual(manifest["benchmark_source"]["image_count"], 1)
        self.assertEqual(json.loads((path.parent / "reference.json").read_text())["comparison_status"], "reference_attached_unscored")
        second = Path(build_packet(self.store, rid))
        self.assertNotEqual(path.parent, second.parent)

    def test_numeric_gate_accepts_observed_dates_but_not_invented_returns(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        tools.dispatch("read_evidence", {"evidence_id": "d1"})
        result = tools.dispatch("compare_windows", {"evidence_id": "s-us-SPY", "windows": [{"start": self.start, "end": self.end, "rationale": "test"}]})
        report = self.report(result["id"])
        report.sections[0].claims[0].text = f"{self.start}부터 {self.end}까지 가격 수익률은 {{{{n1}}}}다."
        errors = check(report, ev, cp)
        self.assertFalse(any(i["code"] == "unbound_number" for i in errors), errors)
        report.sections[0].claims[0].text += " 추가 상승률은 987.65%다."
        self.assertTrue(any(i["code"] == "unbound_number" for i in check(report, ev, cp)))

    def test_schema_output_adapter_and_legacy_response(self):
        from types import SimpleNamespace
        from pipeline import llm
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        opts = dict(system=None, model="haiku", effort=None, tools=(), timeout=20, on_text=None)
        result = {"result": "legacy text", "structured_output": {"ok": True}, "usage": {}, "is_error": False}
        with patch.object(llm, "RUNTIME_DIR", Path(self.tmp.name) / "runtime"), patch.object(llm, "_argv", return_value=["claude", "--tools", ""]), patch.object(llm.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=dumps(result), stderr="")) as process:
            structured = llm._run_claude_code("prompt", **opts, json_schema=schema)
            self.assertEqual(json.loads(structured.text), {"ok": True})
            self.assertIn("--json-schema", process.call_args.args[0])
            self.assertEqual(llm._run_claude_code("prompt", **opts).text, "legacy text")
            with self.assertRaises(ValueError):
                llm._run_claude_code("prompt", **{**opts, "tools": ("WebFetch",)}, json_schema=schema)

    def test_gap_resolution_requires_read_evidence_and_keeps_history(self):
        rid, ev, cp, cfg = self.prepare()
        tools = Toolset(self.store, rid, cp, cfg)
        gap = tools.dispatch("request_data", {"question": "실행 여부", "needed_data": "관련 원문", "why_it_matters": "판단 변경"})["recorded"]
        with self.assertRaises(ValueError):
            tools.dispatch("resolve_gap", {"gap_id": gap["id"], "evidence_ids": ["d1"], "resolution": "확인"})
        tools.dispatch("read_evidence", {"evidence_id": "d1"})
        resolved = tools.dispatch("resolve_gap", {"gap_id": gap["id"], "evidence_ids": ["d1"], "resolution": "원문에서 현금흐름 확인 여부를 확인"})
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(cp["gaps"][0]["needed_data"], "관련 원문")

    def test_resumed_bundle_preserves_prior_report(self):
        from pipeline.weekly.render import archive_attempt
        rid, _ = self.store.create(self.request())
        Runner(self.store, self.fake_model).execute(rid)
        folder = self.store.directory(rid)
        before = (folder / "briefing.json").read_bytes()
        archive_attempt(folder, 1)
        self.assertEqual((folder / "briefing-attempt-1.json").read_bytes(), before)
        self.assertIn('href="run-attempt-1.json"', (folder / "briefing-attempt-1.html").read_text())


if __name__ == "__main__":
    unittest.main()

"""Saved searches, provenance-preserving cases, and explicitly requested research."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import threading
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from models.market_analysis import AnalysisSpec, RunRequest
from .discovery_store import DiscoveryStore
from .store import Conflict, encode
from .strategies import CATALOG_VERSION, catalog

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "logs" / "market-discovery"
ACTIVE = {"queued", "running"}


class DiscoveryService:
    def __init__(self, analysis, root=DEFAULT_ROOT, source_db=None, packet_builder=None, synthesizer=None,
                 preparer=None):
        self.analysis = analysis
        self.store = DiscoveryStore(Path(root))
        if source_db is None:
            from config import DB_PATH
            source_db = DB_PATH
        self.source_db = Path(source_db)
        self.packet_builder = packet_builder
        self.synthesizer = synthesizer
        self.preparer = preparer
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._start_lock = threading.Lock()

    def verified_run(self, run_id):
        state = self.analysis.store.read(run_id)
        result = state.get("result") or {}
        if (state.get("status") not in {"completed", "partial"}
                or state.get("phase") != "finished"
                or result.get("verification", {}).get("status") != "matched"
                or not result.get("spec") or not result.get("snapshot_id")):
            raise Conflict("독립 계산으로 검증된 검색 결과에서 저장·조사를 시작해 주세요.")
        return state

    def _version(self, request, number):
        state = self.verified_run(request["source_run_id"])
        result = state["result"]
        if result.get("unsupported_conditions") or state.get("_unsupported"):
            raise Conflict("해석하지 못한 조건이 남아 있습니다. 지원되는 조건으로 새 검색을 확인한 뒤 저장해 주세요.")
        # Preserve the historical definition verbatim. Validate separately at execution.
        return {"number": number, "spec": copy.deepcopy(result["spec"]),
                "question": state["question"], "date_policy": request["date_policy"],
                "source_run_id": state["id"], "as_of": result["as_of"],
                "snapshot_id": result["snapshot_id"], "created_at": self.store.fresh()["created_at"],
                "catalog_version": result.get("catalog_version"), "skill_version": result.get("skill_version"),
                "expression_version": result.get("expression_version"),
                "verification": copy.deepcopy(result["verification"]),
                "warnings": result.get("warnings", []), "counts": result.get("counts", {}),
                "name": request["name"], "purpose": request["purpose"]}

    def save_strategy(self, request, strategy_id=None):
        def create(conn):
            if strategy_id:
                item = self.store._get(conn, "strategy", strategy_id)
                if item["current_version"] != request["expected_version"]:
                    raise Conflict("전략의 새 버전이 있습니다. 다시 불러온 뒤 저장해 주세요.")
                version = item["current_version"] + 1
            else:
                item = self.store.fresh(versions=[])
                version = 1
            item["versions"].append(self._version(request, version))
            item.update(name=request["name"], purpose=request["purpose"], current_version=version)
            return item
        return self.store.once(f"strategy:{strategy_id or 'new'}", request, "strategy", create)

    def run_strategy(self, strategy_id, request):
        def command(conn):
            saved = self.store._get(conn, "strategy", strategy_id)
            version_no = request.get("version") or saved["current_version"]
            version = next((v for v in saved["versions"] if v["number"] == version_no), None)
            if version is None:
                raise ValueError("저장된 전략 버전이 없습니다.")
            spec = copy.deepcopy(version["spec"])
            spec["as_of"] = version["as_of"] if version["date_policy"] == "fixed" else None
            payload = {"question": version["question"], "spec": AnalysisSpec.model_validate(spec).model_dump(mode="json"),
                       "request_key": "saved-" + hashlib.sha256(f"{strategy_id}:{request['request_key']}".encode()).hexdigest()}
            if version["date_policy"] == "fixed":
                payload.pop("spec")
                payload.update(parent_run_id=version["source_run_id"], date_policy="same", scope="universe", spec_patch={})
            return self.store.fresh(payload=payload, strategy_id=strategy_id, version=version_no,
                                    name=version["name"], date_policy=version["date_policy"])
        resolved = self.store.once(f"strategy-run:{strategy_id}", request, "command", command)
        run = self.analysis.create(RunRequest.model_validate(resolved["payload"]).model_dump(mode="json"))
        state = self.analysis.store.mutate(run["id"], lambda state: state.update(saved_strategy={
            "id": strategy_id, "version": resolved["version"], "name": resolved["name"], "date_policy": resolved["date_policy"]}))
        return self.analysis.store.public(state)

    def recommendations(self, run_id=None, stock_code=None):
        templates = [
            ("trend-volume", "정배열 + 거래량 증가", "지속되는 추세에 거래가 붙는 후보 발견", ["sma_bullish_order", "volume_increase"]),
            ("new-high", "52주 신고가", "긴 박스권을 벗어나는 종목 조사", ["high_52w"]),
            ("trend-transition", "중기 추세 전환", "중기 방향이 바뀐 기업의 새 재료 조사", ["golden_cross_20_60"]),
            ("liquid-trend", "정배열 중 거래량 상위", "거래가 활발한 추세 후보 발견", ["sma_bullish_order", "rank_volume"]),
        ]
        definitions = {item["id"]: item for item in catalog()}
        items = []
        for key, name, purpose, ids in templates:
            spec = AnalysisSpec.model_validate({"mode": "catalog", "strategy_conditions": [
                {"strategy_id": code, "params": definitions[code]["defaults"], "within_days": 1} for code in ids]}).model_dump(mode="json")
            items.append({"id": key, "name": name, "purpose": purpose,
                          "reason": "보유 일봉으로 계산하는 목적별 탐색 예시입니다. 성과 순위에 따른 추천이 아닙니다.",
                          "limitations": ["종목별 이력 부족·가격 보정·관측 거래일의 한계는 실행 결과에서 확인합니다.",
                                           "기술적 신호만으로 자금 유입의 원인을 확인할 수 없습니다."],
                          "spec": spec, "availability": "일봉 도구 지원 · 종목별 자료 충족 여부는 실행 시 판정",
                          "catalog_version": CATALOG_VERSION})
        if bool(run_id) != bool(stock_code):
            raise ValueError("역방향 추천에는 원 실행과 종목코드가 모두 필요합니다.")
        if run_id:
            state, candidate = self._candidate(run_id, stock_code)
            result = state["result"]
            spec = copy.deepcopy(result["spec"])
            spec["as_of"] = None
            # A reverse suggestion repeats the verified structure, not tuned stock-specific thresholds.
            spec.pop("universe_codes", None)
            items.append({"id": "observed-signals", "name": f"{candidate['name']}의 발견 조건으로 탐색",
                          "purpose": "선택 종목과 같은 관측 조건을 가진 후보 발견",
                          "reason": f"{result['as_of']} 기준 이 종목을 실제 선별한 검증 조건을 재사용합니다.",
                          "limitations": ["선택 종목의 향후 수익이나 조건의 우수성을 의미하지 않습니다.",
                                           "종목 한정 범위를 제거하고 전체 시장의 최신 보유 데이터에서 재계산합니다."],
                          "spec": spec, "availability": "원 실행 독립 검증 완료 · 최신 자료 범위는 재실행 시 확인",
                          "evidence": candidate.get("checks") or candidate, "source_run_id": run_id})
        return items

    def run_recommendation(self, recommendation_id, request):
        def command(_conn):
            item = next((r for r in self.recommendations(request.get("run_id"), request.get("stock_code"))
                         if r["id"] == recommendation_id), None)
            if item is None:
                raise FileNotFoundError(recommendation_id)
            return self.store.fresh(payload={"question": item["purpose"], "spec": item["spec"],
                "request_key": "recommended-" + hashlib.sha256(f"{recommendation_id}:{request['request_key']}".encode()).hexdigest()})
        resolved = self.store.once(f"recommendation:{recommendation_id}", request, "command", command)
        return self.analysis.create(RunRequest.model_validate(resolved["payload"]).model_dump(mode="json"))

    def _candidate(self, run_id, stock_code):
        state = self.verified_run(run_id)
        candidate = next((c for c in state["result"].get("items", []) if c["code"] == stock_code), None)
        if candidate is None:
            raise ValueError("원 검색에서 실제 선별된 종목만 조사에 연결할 수 있습니다.")
        return state, candidate

    def create_case(self, request):
        def create(_conn):
            # Opening the same candidate again reuses its workspace and initial
            # job, including across tabs with different request keys.
            if request.get("start_research"):
                for row in _conn.execute("SELECT body FROM records WHERE kind='case'"):
                    previous = json.loads(row[0])
                    if (previous["source_run_id"] == request["run_id"]
                            and previous["stock_code"] == request["stock_code"]
                            and previous["question"] == request["question"]):
                        queue_initial(_conn, previous)
                        return previous
            state, candidate = self._candidate(request["run_id"], request["stock_code"])
            result = state["result"]
            item = self.store.fresh(stock_code=candidate["code"], name=candidate["name"],
                source_run_id=state["id"], question=request["question"], notes=[],
                discovery={"question": state["question"], "spec": result["spec"], "as_of": result["as_of"],
                    "snapshot_id": result["snapshot_id"], "evidence": candidate,
                    "verification": result["verification"], "warnings": result.get("warnings", []),
                    "unsupported_conditions": result.get("unsupported_conditions", []),
                    "counts": result.get("counts", {}), "lineage": state.get("lineage"),
                    "saved_strategy": state.get("saved_strategy")})
            if request.get("start_research"):
                queue_initial(_conn, item)
            return item
        def queue_initial(conn, item):
            for row in conn.execute("SELECT body FROM records WHERE kind='research'"):
                if json.loads(row[0])["case_id"] == item["id"]:
                    return
            # Case and initial job commit atomically. Reload/retries never rerun
            # completed, failed or cancelled jobs; explicit research POST does.
            self.store.put(conn, "research", self._new_research(item, request["question"], None))
        item = self.store.once("case:new", request, "case", create)
        if request.get("start_research"):
            self.start()
            self._wake.set()
        return self.case(item["id"])

    def case(self, case_id):
        item = self.store.get("case", case_id)
        item["research_runs"] = [r for r in self.store.list("research") if r["case_id"] == case_id]
        return item

    def cases(self):
        return [self.case(c["id"]) for c in self.store.list("case")]

    def save_note(self, case_id, request):
        def update(conn):
            item = self.store._get(conn, "case", case_id)
            if len(item["notes"]) != request["expected_revision"]:
                raise Conflict("다른 창에서 판단 기록이 갱신됐습니다. 최신 기록을 불러와 주세요.")
            note = self.store.fresh(revision=len(item["notes"]) + 1,
                                   **{k: request[k] for k in ("reason", "assumptions", "invalidation", "watch_items")})
            item["notes"].append(note)
            return item
        self.store.once(f"note:{case_id}", request, "case", update)
        return self.case(case_id)

    def research(self, case_id, request):
        def create(conn):
            item = self.store._get(conn, "case", case_id)
            # Capture the user's actual note revision at the time of this request.
            return self._new_research(item, request["question"], request.get("as_of"))
        result = self.store.once(f"research:{case_id}", request, "research", create)
        self.start()
        self._wake.set()
        return result

    def _new_research(self, item, question, as_of):
        from .discovery_preparation import pending_preparation
        # Research defaults to today's knowledge, not the last trading day of
        # its originating screen. Pin it at request time, even across midnight.
        day = as_of or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        return self.store.fresh(case_id=item["id"], status="queued", phase="preparing", question=question,
                                as_of=day, note_revision=len(item["notes"]), error=None,
                                preparation=pending_preparation())

    def cancel(self, case_id, research_id):
        def change(item):
            if item["case_id"] != case_id:
                raise FileNotFoundError(research_id)
            if item["status"] in ACTIVE:
                item["status"] = "cancelled"
                if item.get("preparation", {}).get("status") in {"pending", "running"}:
                    item["preparation"]["status"] = "cancelled"
        return self.store.mutate("research", research_id, change)

    @staticmethod
    def changes(packet, previous):
        def evidence(value):
            return {item["id"]: hashlib.sha256(encode(item)).hexdigest()
                    for lane in (value or {}).get("lanes", []) for item in lane.get("items", [])}
        old = evidence((previous or {}).get("packet"))
        new = evidence(packet)
        return {"previous_run_id": (previous or {}).get("id"),
                "added_ids": sorted(new.keys() - old.keys()), "removed_ids": sorted(old.keys() - new.keys()),
                "changed_ids": sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
                "meaning": "선택된 자료 묶음의 변화입니다. 자료 제거·진위 변화·전체 시장의 새 소식을 뜻하지 않습니다."}

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, name="discovery-research", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=8)

    def _worker(self):
        fd = os.open(self.store.root / "worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            for item in self.store.list("research"):
                if item["status"] == "running":
                    self.store.mutate("research", item["id"], lambda r: r.update(
                        status="interrupted", error="서버가 중단되었습니다. 새 조사로 다시 실행할 수 있습니다."))
            while not self._stop.is_set():
                pending = [r for r in self.store.list("research") if r["status"] == "queued"]
                if pending:
                    self._execute(pending[-1]["id"])
                else:
                    self._wake.wait(1)
                    self._wake.clear()
        finally:
            os.close(fd)

    def _execute(self, research_id):
        from .discovery_research import build_packet, synthesize
        from .discovery_preparation import prepare_company, PreparationCancelled
        def cancelled():
            return self._stop.is_set() or self.store.get("research", research_id)["status"] == "cancelled"
        def running(item):
            if item["status"] == "queued":
                item["status"] = "running"
        run = self.store.mutate("research", research_id, running)
        if run["status"] != "running":
            return
        try:
            case = self.case(run["case_id"])
            case["notes"] = case["notes"][:run["note_revision"]]
            previous = next((r for r in case["research_runs"] if r["id"] != research_id and r.get("packet")
                             and r["created_at"] < run["created_at"]), None)
            def progress(preparation):
                self.store.mutate("research", research_id, lambda r: r.update(preparation=preparation)
                                  if r["status"] == "running" else None)
            preparation = (self.preparer or prepare_company)(self.source_db, self.store.root, case,
                as_of=run["as_of"], progress=progress, cancel=cancelled)
            if cancelled():
                return
            self.store.mutate("research", research_id, lambda r: r.update(phase="reading", preparation=preparation)
                              if r["status"] == "running" else None)
            if self.packet_builder:
                packet = self.packet_builder(self.source_db, case, question=run["question"], as_of=run["as_of"])
            else:
                packet = build_packet(self.source_db, case, question=run["question"], as_of=run["as_of"], preparation=preparation)
            packet["preparation"] = preparation
            packet.setdefault("warnings", []).extend(f"{item['label']}: {item['detail']}" for item in preparation.get("items", [])
                if item["status"] in {"failed", "unpublished"})
            if cancelled():
                return
            self.store.mutate("research", research_id, lambda r: r.update(phase="analyzing", packet=packet, changes=self.changes(packet, previous))
                              if r["status"] == "running" else None)
            result = (self.synthesizer or synthesize)(packet, cancel=cancelled)
            def finish(item):
                item["model_diagnostics"] = {key: result[key] for key in
                    ("cost_usd", "attempts", "validation_errors") if key in result}
                if item["status"] == "running" and not self._stop.is_set():
                    partial = bool(packet.get("warnings")) or any(lane["status"] != "complete" for lane in packet["lanes"])
                    item.update(result=result, status="partial" if partial else "completed", phase="complete")
            self.store.mutate("research", research_id, finish)
        except PreparationCancelled:
            pass
        except Exception as exc:
            def fail(item):
                diagnostics = {key: getattr(exc, key) for key in
                    ("cost_usd", "known_cost_usd", "attempts", "validation_errors") if hasattr(exc, key)}
                if diagnostics:
                    item["model_diagnostics"] = diagnostics
                if item["status"] == "running":
                    item.update(status="interrupted" if self._stop.is_set() else "failed", error=str(exc)[:1500])
            self.store.mutate("research", research_id, fail)
        finally:
            if self._stop.is_set():
                self.store.mutate("research", research_id, lambda r: r.update(status="interrupted", error="서버 종료로 조사가 중단되었습니다.")
                                  if r["status"] == "running" else None)

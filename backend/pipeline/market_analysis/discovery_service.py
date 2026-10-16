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
from .strategies import CATALOG_VERSION, catalog, normalize_condition

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "logs" / "market-discovery"
ACTIVE = {"queued", "running"}


PHRASES = {
    "trend-volume": "5·20·60일 이동평균이 정배열이고 전일 대비 거래량이 증가",
    "liquid-trend": "5·20·60일 이동평균이 정배열인 종목 중 거래량 상위 20개",
    "trend-strength": "5·20·60일 이동평균이 정배열인 종목 중 20일 수익률 상위 20개",
    "new-high": "52주 신고가를 기록",
    "high-20d-volume": "20일 신고가를 갱신하고 전일 대비 거래량이 증가",
    "ytd-high": "연중 신고가를 기록",
    "profile-breakout": "최근 5거래일 안에 20일 매물대를 상향 돌파",
    "pullback": "최근 5거래일 안에 10일 신고가를 돌파한 뒤 1% 되돌림",
    "trend-transition": "최근 5거래일 안에 20일 이동평균이 60일 이동평균을 골든크로스",
    "short-cross": "최근 5거래일 안에 5일 이동평균이 20일 이동평균을 골든크로스",
    "slope-up": "최근 5거래일 안에 20일 이동평균이 상승 반전",
    "reversal-confirmed": "최근 5거래일 안에 20일 기준 추세전환이 3일 연속 확인",
    "macd-zero": "최근 5거래일 안에 MACD(12,26,9)가 0선을 상향 돌파",
    "stochastic-buy": "최근 5거래일 안에 Stochastic slow(10,5,5) 과매도 매수 신호 발생",
    "low-52w": "52주 신저가를 기록",
    "volume-growth": "거래량 증가율 상위 20개",
    "lens-range-break": "고점·저점이 수평인 박스권이면서 최근 5거래일 안에 전고점을 상향 돌파",
    "lens-spring": "최근 5거래일 안에 전저점을 이탈한 뒤 다시 위로 마감(거짓 하향 이탈)",
    "lens-pullback-20": "200일 이동평균 위에 있고 20일 이격도가 98.5~101.5",
    "lens-squeeze": "볼린저 밴드폭이 120봉 최소(스퀴즈)",
    "lens-oversold-exit": "최근 10거래일 안에 RSI(14)가 30을 위로 벗어났고 저점이 높아지는 중",
    "lens-momentum-strong": "12-1 모멘텀이 양이고 ADX(14) 25 이상이며 200일 이동평균 위",
    "lens-profile-above": "최근 5거래일 안에 60일 매물대 중심선을 상향 돌파했고 200일 이동평균 위",
    "lens-reenter-lower": "최근 5거래일 안에 볼린저 하단 밖에서 안으로 복귀",
}

# 상황 렌즈(D-198): 지표 이름을 모르는 사용자가 '상황'으로 고르는 조합. (id, 이름, 보는 것, 못 보는 것, [(strategy_id, within, params)])
LENSES = [
    ("lens-range-break", "박스권 상단을 막 넘은 종목", "고점·저점이 수평이던 박스의 상단을 최근 5거래일 안에 종가로 넘은 종목",
     "넘은 뒤 되돌아올지(거짓 돌파)는 며칠 뒤에야 판정됩니다.", [("trading_range", 1, {}), ("resistance_break", 5, {})]),
    ("lens-spring", "바닥을 깨는 듯하다 되돌아온 종목(스프링)", "직전 저점을 종가로 깼다가 곧 다시 위로 마감한 종목",
     "매집인지 분산인지, 왜 되돌아왔는지는 판정하지 않습니다.", [("false_breakdown", 5, {})]),
    ("lens-pullback-20", "장기 추세 위에서 20일선까지 되돌아온 종목", "200일선 위에 있으면서 종가가 20일선 ±1.5% 안으로 내려온 종목",
     "되돌림이 여기서 멈출지는 알 수 없습니다.", [("close_above_sma", 1, {}), ("disparity_low", 1, {"threshold_pct": 101.5}), ("disparity_high", 1, {"threshold_pct": 98.5})]),
    ("lens-squeeze", "변동성이 가장 좁아진 종목(볼린저 스퀴즈)", "볼린저 밴드폭이 최근 120봉 중 가장 좁은 종목",
     "좁아진 뒤 어느 방향으로 벌어질지는 말하지 않습니다.", [("bollinger_squeeze", 1, {})]),
    ("lens-oversold-exit", "과매도에서 빠져나오며 저점을 높이는 종목", "RSI가 30을 위로 벗어났고(10거래일 안) 스윙 저점이 높아지는 종목",
     "반등의 이유와 지속 여부는 보지 않습니다.", [("rsi_exit_oversold", 10, {}), ("higher_lows", 1, {})]),
    ("lens-momentum-strong", "1년 모멘텀이 양이고 추세가 강한 종목", "12-1 모멘텀 양, ADX 25 이상, 200일선 위를 모두 만족",
     "모멘텀이 언제 꺾일지는 보지 않습니다. 강한 추세는 이미 많이 오른 뒤일 수 있습니다.", [("momentum_up", 1, {}), ("adx_strong_trend", 1, {}), ("close_above_sma", 1, {})]),
    ("lens-profile-above", "매물대 위로 올라선 종목", "60일 매물대 중심선을 최근 5거래일 안에 넘었고 200일선 위인 종목",
     "매물대는 일봉 근사라 체결가별 실제 매물이 아닙니다.", [("volume_profile_up_60d", 5, {}), ("close_above_sma", 1, {})]),
    ("lens-reenter-lower", "볼린저 하단 밖에서 안으로 복귀한 종목", "종가가 하단 밖에 있다가 최근 5거래일 안에 밴드 안으로 돌아온 종목",
     "밴드 접촉·복귀 자체는 반전 신호가 아닙니다(Bollinger 규칙).", [("bollinger_reenter_lower", 5, {})]),
]


class DiscoveryService:
    def __init__(self, analysis, root=DEFAULT_ROOT, source_db=None, packet_builder=None, synthesizer=None, web_collector=None,
                 preparer=None):
        self.analysis = analysis
        self.store = DiscoveryStore(Path(root))
        if source_db is None:
            from config import DB_PATH
            source_db = DB_PATH
        self.source_db = Path(source_db)
        self.packet_builder = packet_builder
        self.synthesizer = synthesizer
        self.web_collector = web_collector  # 테스트 주입; 기본은 company_profile.ensure_profile
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
        # (id, 그룹, 이름, 목적, [(strategy_id, within_days)]) — 보유 일봉으로 계산하는 목적별 예시. PHRASES는 입력창에 덧붙이는 조건 문장.
        # 상태 조건은 기준일(1), 사건 조건(교차·돌파·반전)은 최근 5거래일 안 발생으로 잡아 후보를 확보한다.
        templates = [
            ("trend-volume", "추세 지속", "정배열 + 거래량 증가", "지속되는 추세에 거래가 붙는 후보 발견", [("sma_bullish_order", 1), ("volume_increase", 1)]),
            ("liquid-trend", "추세 지속", "정배열 중 거래량 상위", "거래가 활발한 추세 후보 발견", [("sma_bullish_order", 1), ("rank_volume", 1)]),
            ("trend-strength", "추세 지속", "정배열 중 20일 수익률 상위", "최근 한 달 가장 강했던 추세 종목 발견", [("sma_bullish_order", 1), ("rank_return_20d", 1)]),
            ("new-high", "돌파·신고가", "52주 신고가", "긴 박스권을 벗어나는 종목 조사", [("high_52w", 1)]),
            ("high-20d-volume", "돌파·신고가", "20일 신고가 + 거래량 증가", "단기 고점을 거래량과 함께 넘는 후보 발견", [("high_20d", 1), ("volume_increase", 1)]),
            ("ytd-high", "돌파·신고가", "연중 신고가", "올해 최고가를 새로 쓴 종목 조사", [("high_ytd", 1)]),
            ("profile-breakout", "돌파·신고가", "20일 매물대 상향돌파", "저항 구간을 최근 5거래일 안에 넘은 후보 발견", [("volume_profile_up_20d", 5)]),
            ("pullback", "돌파·신고가", "신고가 돌파 후 눌림", "10일 신고가를 넘긴 뒤 1% 되돌린 종목 관찰", [("breakout_pullback_10d", 5)]),
            ("trend-transition", "추세 전환", "중기 추세 전환", "중기 방향이 바뀐 기업의 새 재료 조사", [("golden_cross_20_60", 5)]),
            ("short-cross", "추세 전환", "단기 골든크로스(5,20)", "짧은 조정 뒤 다시 방향을 잡는 종목 발견", [("golden_cross_5_20", 5)]),
            ("slope-up", "추세 전환", "20일 이평 상승반전", "하락하던 중기선이 고개를 든 종목 조사", [("sma_slope_up_20d", 5)]),
            ("reversal-confirmed", "추세 전환", "추세전환 확인형", "전환 뒤 며칠 유지된 종목만 추리기", [("trend_reversal_confirmed", 5)]),
            ("macd-zero", "모멘텀 지표", "MACD 0선 상향돌파", "모멘텀이 플러스로 넘어온 종목 발견", [("macd_zero_cross", 5)]),
            ("stochastic-buy", "모멘텀 지표", "Stochastic 과매도 매수 신호", "짧은 과매도 뒤 반등 초입 후보 관찰", [("stochastic_slow_buy", 5)]),
            ("low-52w", "바닥·역발상", "52주 신저가", "장기 바닥권에 있는 기업의 사정 조사", [("low_52w", 1)]),
            ("volume-growth", "거래 활황", "거래량 증가율 상위", "전일 대비 거래가 가장 크게 늘어난 종목 관찰", [("rank_volume_growth", 1)]),
        ]
        definitions = {item["id"]: item for item in catalog()}
        items = []
        generic = ["종목별 이력 부족·가격 보정·관측 거래일의 한계는 실행 결과에서 확인합니다.",
                   "기술적 신호만으로 자금 유입의 원인을 확인할 수 없습니다."]
        entries = [(key, group, name, purpose, None, [(code, within, {}) for code, within in conditions]) for key, group, name, purpose, conditions in templates]
        entries += [(key, "상황 렌즈", name, purpose, misses, conditions) for key, name, purpose, misses, conditions in LENSES]
        for key, group, name, purpose, misses, conditions in entries:
            normalized = [normalize_condition({"strategy_id": code, "params": {**definitions[code]["defaults"], **params}, "within_days": within})
                          for code, within, params in conditions]
            spec = AnalysisSpec.model_validate({"mode": "catalog", "strategy_conditions": normalized}).model_dump(mode="json")
            items.append({"id": key, "group": group, "name": name, "purpose": purpose, "phrase": PHRASES.get(key), "misses": misses,
                          "reason": "보유 일봉으로 계산하는 목적별 탐색 예시입니다. 성과 순위에 따른 추천이 아닙니다.",
                          "limitations": ([misses] if misses else []) + generic,
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
            self.store.put(conn, "research", self._new_research(item, request["question"], None, request.get("web", True)))
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
            return self._new_research(item, request["question"], request.get("as_of"), request.get("web", True))
        result = self.store.once(f"research:{case_id}", request, "research", create)
        self.start()
        self._wake.set()
        return result

    def _new_research(self, item, question, as_of, web=True):
        from .discovery_preparation import pending_preparation
        # Research defaults to today's knowledge, not the last trading day of
        # its originating screen. Pin it at request time, even across midnight.
        day = as_of or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        return self.store.fresh(case_id=item["id"], status="queued", phase="preparing", question=question,
                                as_of=day, note_revision=len(item["notes"]), error=None, web=bool(web),
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

    def _web_step(self, case, run, preparation, progress, cancelled):
        """웹 조사 레인(D-188): DART 수집(90초 예산)과 분리된 별도 단계. 실패는 레인 상태로만 남긴다."""
        from datetime import date as _date
        item = next((i for i in preparation.get("items", []) if i["id"] == "web"), None)
        if item is None:
            return preparation
        def publish(status, detail):
            item.update(status=status, detail=detail)
            progress(preparation)
        if not run.get("web", True):
            publish("skipped", "이번 조사에서는 웹 확인을 생략했습니다.")
            return preparation
        if run.get("as_of") and _date.fromisoformat(run["as_of"]) < datetime.now(ZoneInfo("Asia/Seoul")).date():
            publish("unsupported", "과거 시점 조사에서는 새 웹 조사를 하지 않습니다. 저장된 발췌만 읽습니다.")
            return preparation
        publish("collecting", "웹에서 사업보고서·IR·뉴스·리포트를 조사하고 있습니다(최대 3분).")
        try:
            collector = self.web_collector
            if collector is None:
                from pipeline.company_profile import ensure_profile as collector
            profile, reused = collector(case["stock_code"], case.get("name") or case["stock_code"], None,
                                        (case.get("discovery") or {}).get("question"), cancel=cancelled)
            count = len(profile.get("sources", []))
            if count == 0:
                publish("unpublished", "웹 조사에서 인용할 수 있는 출처를 확보하지 못했습니다.")
            else:
                publish("available" if reused else "collected",
                        f"{'최근 24시간 보고서 재사용' if reused else '새 조사'} · 출처 {count}건 · " + (profile.get("overview") or "")[:120])
        except Exception as exc:
            if cancelled():
                return preparation
            publish("failed", f"웹 조사 실패: {str(exc)[:200]}")
        return preparation

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
            preparation = self._web_step(case, run, preparation, progress, cancelled)
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

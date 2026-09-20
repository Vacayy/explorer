"""Host-side tool registry. Every argument is validated before dispatch."""
from datetime import date, timedelta
from typing import Literal

from pydantic import Field, model_validator

from models.weekly import Hypothesis, StrictModel
from . import calculations
from .evidence import Evidence, instant
from .sources import FRED_SERIES, OFFICIAL_DOMAINS
from .store import atomic_write, dumps
from .worker import isolated


class Empty(StrictModel):
    pass


class Find(StrictModel):
    query: str = Field(default="", max_length=300)
    limit: int = Field(default=8, ge=1, le=20)
    offset: int = Field(default=0, ge=0, le=1000)
    source: str | None = Field(default=None, max_length=30)
    since: date | None = None


class Read(StrictModel):
    evidence_id: str
    start: int = Field(default=0, ge=0, le=10_000_000)
    length: int = Field(default=16000, ge=100, le=24000)


class Window(StrictModel):
    start: date
    end: date
    rationale: str = Field(min_length=1, max_length=1000)


class Compare(StrictModel):
    evidence_id: str
    windows: list[Window] = Field(min_length=1, max_length=5)
    start_shifts: list[int] = Field(default=[-5, 5], max_length=5)

    @model_validator(mode="after")
    def bounded_shifts(self):
        if any(abs(v) > 60 for v in self.start_shifts):
            raise ValueError("시작점 민감도는 ±60 관측치 이내")
        return self


class Chart(StrictModel):
    evidence_id: str
    start: date
    end: date


class Analogues(StrictModel):
    evidence_id: str
    target_start: date
    target_end: date
    window: int = Field(default=20, ge=5, le=120)
    stride: int = Field(default=5, ge=1, le=60)
    min_separation: int = Field(default=20, ge=5, le=252)
    limit: int = Field(default=5, ge=1, le=12)
    rationale: str = Field(min_length=1, max_length=2000)


class Outcomes(StrictModel):
    selection_id: str
    horizon: int = Field(default=20, ge=1, le=252)


class Fetch(StrictModel):
    provider: Literal["yahoo_prices", "fred", "official_page"]
    ticker: str | None = Field(default=None, pattern=r"^(?:[A-Z]{1,6}(?:-[A-Z])?|\^(?:GSPC|IXIC|DJI|RUT))$")
    series: str | None = None
    start: date | None = None
    end: date | None = None
    url: str | None = Field(default=None, max_length=2000)
    purpose: str = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def provider_fields(self):
        if self.provider == "official_page":
            if not self.url or any(v is not None for v in (self.ticker, self.series, self.start, self.end)):
                raise ValueError("official_page에는 url만 지정하세요")
        else:
            if not self.start or not self.end or self.start >= self.end:
                raise ValueError("가격/통계에는 start < end가 필요합니다")
            if (self.end - self.start).days > 3650:
                raise ValueError("한 요청은 10년 이내로 제한합니다")
            if self.provider == "yahoo_prices" and (not self.ticker or self.series or self.url):
                raise ValueError("yahoo_prices에는 미국 ticker와 start/end를 지정하세요")
            if self.provider == "fred" and (self.series not in FRED_SERIES or self.ticker or self.url):
                raise ValueError("지원 FRED 시리즈: " + ", ".join(FRED_SERIES))
        return self


class Decision(StrictModel):
    hypothesis: Hypothesis
    reason: str = Field(min_length=1, max_length=2000)
    alternatives_considered: list[str] = Field(min_length=1, max_length=8)
    next_investigation: str = Field(min_length=1, max_length=1500)


class Gap(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    needed_data: str = Field(min_length=1, max_length=1500)
    why_it_matters: str = Field(min_length=1, max_length=1500)
    possible_source: str = Field(default="", max_length=1000)


class ResolveGap(StrictModel):
    gap_id: str = Field(pattern=r"^g[0-9]+$")
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    resolution: str = Field(min_length=1, max_length=1500)


class Finish(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)


REGISTRY = {
    "coverage": (Empty, "고정한 수집 범위·시점 제약과 추가 확보 공급자를 확인한다."),
    "market_overview": (Empty, "관측일을 명시한 시장 수치와 최근 원문 후보로 핵심 질문을 고른다."),
    "find_evidence": (Find, "cutoff 적격 자료만 검색. 한국어 부분 검색·FTS, 정확한 텍스트 중복 제거. 발췌는 원문 읽기와 다르다."),
    "read_evidence": (Read, "원문/계산을 문자 offset으로 읽는다. 긴 원문의 다음 구간도 확인할 수 있다."),
    "compare_windows": (Compare, "일별 수익률·기울기·변동성·낙폭과 시작점 이동 민감도를 실제 관측일로 계산한다."),
    "render_chart": (Chart, "고정한 가격/지표의 출처·기간·단위가 있는 SVG 차트를 만든다."),
    "find_analogues": (Analogues, "과거 가격 형태 후보·제외·기준을 결과 확인 전에 고정한다. 인과 유사성을 뜻하지 않는다."),
    "evaluate_outcomes": (Outcomes, "고정 후보 전체의 cutoff 이전 후속 결과를 읽는다. 탐색 표본, 확률 추정 금지."),
    "fetch_source": (Fetch, "미국 주식/ETF/지수 가격, 날짜 vintage FRED, 등록 공식 사이트 HTML을 확보한다."),
    "read_events": (Find, "이벤트 관련 원문 후보를 찾는다. published_at을 사건일로 간주하지 말고 원문을 읽는다."),
    "read_memory": (Empty, "cutoff 이전에 생성된 지난 가설·수정 조건. 독립 근거로 인용할 수 없다."),
    "record_decision": (Decision, "질문·가설·대안·변경 조건과 선택 이유를 기록한다. 원시 내적 사고 대신 검토 가능한 요약."),
    "request_data": (Gap, "미확보 데이터의 정의·기간·중요성과 공급자 후보를 남긴다."),
    "resolve_gap": (ResolveGap, "이후 실제 읽은 근거로 해소한 자료 공백을 연결하고 해결 이유를 기록한다."),
    "finish_research": (Finish, "핵심 대안과 필요한 근거를 검토했다면 작성/검토 단계로 전환한다."),
}


def schemas():
    return [{"name": name, "description": desc, "input_schema": cls.model_json_schema()} for name, (cls, desc) in REGISTRY.items()]


def action_schema():
    definitions, variants = {}, []
    for name, (cls, _) in REGISTRY.items():
        args = cls.model_json_schema()
        definitions.update(args.pop("$defs", {}))
        variants.append({"type": "object", "additionalProperties": False,
                         "properties": {"tool": {"const": name, "type": "string"}, "args": args,
                                        "question": {"type": "string", "minLength": 1, "maxLength": 1500},
                                        "reason": {"type": "string", "minLength": 1, "maxLength": 2000}},
                         "required": ["tool", "args", "question", "reason"]})
    # Anthropic tool input_schema forbids root-level oneOf; keep the discriminated
    # union inside a required action property. The host unwraps this envelope.
    return {"type": "object", "properties": {"action": {"oneOf": variants}},
            "required": ["action"], "additionalProperties": False, "$defs": definitions}


class Toolset:
    def __init__(self, store, run_id, checkpoint, config, cancelled=lambda: False, remaining=lambda: 1800):
        self.store, self.run_id, self.cp, self.config = store, run_id, checkpoint, config
        self.evidence = Evidence(store.directory(run_id))
        self.cancelled, self.remaining = cancelled, remaining

    def dispatch(self, name, args):
        if name not in REGISTRY:
            raise ValueError("등록되지 않은 도구")
        value = REGISTRY[name][0].model_validate(args)
        return getattr(self, name)(value)

    def _read(self, item, start=0, length=16000):
        self._eligible(item)
        text = item["text"] or dumps(item["data"])
        end = min(len(text), start + length)
        if start >= len(text) and text:
            raise ValueError("원문 offset이 범위를 벗어났습니다")
        ranges = self.cp.setdefault("read_ranges", {}).setdefault(item["id"], [])
        merged = []
        for a, b in sorted([*ranges, [start, end]]):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.cp["read_ranges"][item["id"]] = merged
        if item["id"] not in self.cp["read_ids"]:
            self.cp["read_ids"].append(item["id"])
        return {"id": item["id"], "kind": item["kind"], "meta": item["meta"], "sha256": item["sha256"],
                "text": text[start:end], "start": start, "end": end, "total_length": len(text),
                "next_start": end if end < len(text) else None}

    def _eligible(self, item):
        if self.config["mode"] != "live" and item["meta"].get("temporal_status") == "historical_version_unverified":
            raise ValueError("당시 버전 미검증 자료는 역사 실행의 분석 문맥에서 격리합니다. 보존 snapshot 또는 공개 vintage가 필요합니다")
        return item

    def _derived(self, source, kind, data):
        meta = {"title": kind + " · " + source["meta"]["title"],
                "source_ids": [source["id"]], "source_type": "deterministic_calculation",
                "unit": source["meta"].get("unit"), "metric_kind": source["meta"].get("metric_kind"),
                "temporal_status": source["meta"].get("temporal_status"),
                "warnings": source["meta"].get("warnings", [])}
        return self.evidence.add(kind, meta, data)

    def coverage(self, _):
        return {**self.evidence.coverage(), "providers": {"yahoo_prices": "US daily USD stocks/ETFs: unadjusted-request Close + Adj Close, current provider version",
                "fred": list(FRED_SERIES), "official_page": list(OFFICIAL_DOMAINS)},
                "network_enabled": self.config["allow_network"] and self.config["mode"] != "system_replay"}

    def market_overview(self, _):
        cutoff = instant(self.config["cutoff"])
        series = []
        for item in self.evidence.series():
            points = item["data"]["points"]
            if not points:
                continue
            tail = points[-6:]
            summary = calculations.metrics(tail, metric_kind=item["meta"].get("metric_kind", "level")) if len(tail) >= 2 else {"last": tail[-1]["value"]}
            series.append({"evidence_id": item["id"], "title": item["meta"]["title"], "unit": item["meta"]["unit"],
                           "first_date": points[0]["date"], "last_date": points[-1]["date"], "observations": len(points),
                           "stale_calendar_days": (cutoff.date() - date.fromisoformat(points[-1]["date"])).days,
                           "tail_start": tail[0]["date"], "metrics": summary})
        self.cp["overview_seen"] = True
        return {"series": series, "recent_documents": self.evidence.find(limit=16, since=(cutoff - timedelta(days=8)).isoformat()),
                "note": "tail은 마지막 6개 관측치이며 보고 주간 수익률이 아닙니다. 주간/이벤트 창은 compare_windows로 정의하세요. 현재 수집 목록은 시장 전체 표본이 아닙니다."}

    def find_evidence(self, args):
        return self.evidence.find(**args.model_dump(mode="json", exclude_none=True))

    def read_events(self, args):
        return self.find_evidence(args)

    def read_evidence(self, args):
        return self._read(self.evidence.get(args.evidence_id), args.start, args.length)

    def compare_windows(self, args):
        item = self._eligible(self.evidence.get(args.evidence_id))
        if item["kind"] != "series":
            raise ValueError("계산은 series 근거만 입력할 수 있습니다")
        result = calculations.compare(item, [w.model_dump(mode="json") for w in args.windows], args.start_shifts)
        computed = self._derived(item, "calculation", result)
        self.cp["calculation_seen"] = True
        return self._read(computed, length=24000)

    def render_chart(self, args):
        item = self._eligible(self.evidence.get(args.evidence_id))
        if item["kind"] != "series":
            raise ValueError("차트는 series 입력이 필요합니다")
        svg = calculations.chart_svg(item, str(args.start), str(args.end))
        artifact = self._derived(item, "chart", {"source_id": item["id"], "start": str(args.start), "end": str(args.end)})
        filename = artifact["id"] + ".svg"
        atomic_write(self.evidence.directory / filename, svg)
        self.cp.setdefault("charts", []).append({"file": filename, "source_id": item["id"], "evidence_id": artifact["id"]})
        return {**self._read(artifact), "evidence_id": artifact["id"], "file": filename, "source_id": item["id"],
                "note": "차트 정의/원천 연결을 읽었습니다. 차트는 원천 계열의 표현이며 독립 증거가 아닙니다."}

    def find_analogues(self, args):
        item = self._eligible(self.evidence.get(args.evidence_id))
        data = calculations.select_analogues(item, str(args.target_start), str(args.target_end), args.window,
                                             args.stride, args.min_separation, args.limit, args.rationale)
        data["previous_outcome_inspections"] = self.cp.get("outcome_inspections", 0)
        selection = self._derived(item, "analogue_selection", data)
        self.cp.setdefault("selections", []).append(selection["id"])
        # Entire candidate population remains in the immutable evidence; show selected summaries.
        self.cp["read_ids"].append(selection["id"])
        return {"id": selection["id"], "criteria": data["criteria"], "candidate_count": len(data["candidates"]),
                "selected": [c for c in data["candidates"] if c.get("selected")], "limitations": data["limitations"],
                "previous_outcome_inspections": data["previous_outcome_inspections"]}

    def evaluate_outcomes(self, args):
        if args.selection_id not in self.cp.get("selections", []):
            raise ValueError("이 실행에서 먼저 고정한 후보만 평가할 수 있습니다")
        selection = self.evidence.get(args.selection_id)
        item = self._eligible(self.evidence.get(selection["data"]["source_id"]))
        result = self._derived(item, "analogue_outcomes", calculations.outcomes(selection, item, args.horizon))
        self.cp["outcome_inspections"] = self.cp.get("outcome_inspections", 0) + 1
        return self._read(result, length=24000)

    def fetch_source(self, args):
        if not self.config["allow_network"] or self.config["mode"] == "system_replay" or self.cp.get("resume_count"):
            raise ValueError("이 실행은 외부 확보가 닫혀 있습니다. 새 자료는 새 실행으로 확보하세요")
        payload = args.model_dump(mode="json", exclude_none=True)
        provider = payload.pop("provider")
        purpose = payload.pop("purpose")
        if payload.get("end") and payload["end"] > (instant(self.config["cutoff"]).date() + timedelta(days=1)).isoformat():
            raise ValueError("cutoff 이후 데이터는 요청할 수 없습니다")
        # Cache only within the frozen run, not the operating cache_meta table.
        key = dumps({"provider": provider, "args": payload})
        cached = self.cp.setdefault("source_cache", {}).get(key)
        if cached:
            return self._read(self.evidence.get(cached))
        fetched = isolated("source", {"provider": provider, "args": payload, "cutoff": self.config["cutoff"], "mode": self.config["mode"]},
                           timeout=min(90, self.remaining()), cancelled=self.cancelled)
        fetched["meta"]["acquisition_purpose"] = purpose
        item = self.evidence.add(**fetched)
        self.cp["source_cache"][key] = item["id"]
        return self._read(item)

    def read_memory(self, _):
        if "memory" not in self.cp:
            self.cp["memory"] = self.store.memory(self.config["cutoff"], self.run_id)
        return self.cp["memory"]

    def record_decision(self, args):
        for eid in args.hypothesis.evidence_ids:
            if eid not in self.cp["read_ids"]:
                raise ValueError(f"읽지 않은 근거를 판단에 연결할 수 없습니다: {eid}")
        record = args.model_dump(mode="json")
        record["revision"] = 1 + sum(d["hypothesis"]["id"] == args.hypothesis.id for d in self.cp["decisions"])
        self.cp["decisions"].append(record)
        return {"recorded": True, "hypothesis_id": args.hypothesis.id, "revision": record["revision"]}

    def request_data(self, args):
        gap = args.model_dump(mode="json")
        gap.update(id="g" + str(len(self.cp["gaps"]) + 1), status="open")
        self.cp["gaps"].append(gap)
        return {"recorded": gap, "status": "unavailable_requires_new_adapter_or_access"}

    def resolve_gap(self, args):
        for eid in args.evidence_ids:
            if eid not in self.cp["read_ids"]:
                raise ValueError("실제로 읽은 근거로만 공백을 해결할 수 있습니다")
            self._eligible(self.evidence.get(eid))
        gap = next((g for g in self.cp["gaps"] if g.get("id") == args.gap_id), None)
        if gap is None:
            raise ValueError("공백 ID를 찾을 수 없습니다")
        gap.update(status="resolved", evidence_ids=args.evidence_ids, resolution=args.resolution)
        return gap

    def finish_research(self, args):
        if not self.cp["decisions"] or not self.cp["read_ids"]:
            raise ValueError("최소한 원문 근거를 읽고 핵심 판단과 대안을 기록해야 합니다")
        return {"finished": True, "reason": args.reason}

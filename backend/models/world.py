"""월드모델 읽기 전용 응답 (docs/specs/world-model.md). 전부 저장분 조회 — LLM 없음."""
from typing import Literal

from pydantic import BaseModel


class MegaItem(BaseModel):
    id: int
    name: str
    title: str | None
    narrative: str | None
    members: list[str]
    version: int
    created_at: str | None
    mt_topics: int        # 이번 주 Market Today 연결 화두 수(멤버 서사끼리 중복 제거, 마감 정리 제외) — ia-redesign §9·§4.25
    mt_sessions: int      # 이번 주 연결 회차 수
    boost: bool           # 멤버 중 '다음 갱신 앞당김' 서사가 있다


class StoredWorldview(BaseModel):
    briefing: str | None
    created_at: str | None
    stale: bool              # 입력(지식·주간 신호)이 저장 이후 바뀜 — 갱신은 지식 화면에서만


class BigPictureInputs(BaseModel):
    narratives: int        # 최근 7일 새 내러티브 버전
    mt_sessions: int       # 최근 7일 Market Today 회차
    overnight_days: int    # 최근 7일 Overnight(us_briefings) 일수


class NarrativeChip(BaseModel):
    narrative_id: int
    topic: str
    version: int
    created_at: str | None
    is_new: bool             # 그 주(생성 기준 7일 안)에 첫 버전이 나온 서사


class StrandEvidence(BaseModel):
    kind: Literal["market_today", "overnight"]
    ref: str                 # mt:<market_today.id>:<화두 순번> | ov:<trade_date>:<key_points 순번> — 저장은 id만
    label: str               # 'Market Today 11/4 15:40' · 'Overnight 11/3'
    text: str                # 읽을 때 원천에서 꺼낸 원문 한 줄(화두 제목 · 핵심 요약)
    date: str


class Strand(BaseModel):
    title: str
    status: Literal["strengthening", "mixed", "weakening", "new"]   # 강해짐 · 엇갈림 · 약해짐 · 새로
    narratives: list[NarrativeChip]
    mt_topics: int           # 이번 주 Market Today 연결 화두 수(줄기 서사끼리 중복 제거, 마감 정리 제외)
    mt_sessions: int
    boost: bool              # 줄기 서사 중 '다음 갱신 앞당김'
    evidence: list[StrandEvidence]


class ShakenBy(NarrativeChip):
    quote: str               # 그 서사 제목·3줄 요약에서 글자 그대로 확인된 인용


class PremiseItem(BaseModel):
    text: str
    shaken_by: ShakenBy | None   # 이번 주 흔들림 — 부딪힌 서사(흔들린 전제에만)


class Premises(BaseModel):
    settled: list[PremiseItem]     # 자리 잡은 전제
    contested: list[PremiseItem]   # 흔들린 전제


class RebuildState(BaseModel):
    available: bool
    reason: Literal["cooldown", "budget", "unavailable"] | None
    retry_at: str | None             # UTC DB 표기 — 쿨다운·예산이 풀리는 시각
    budget_left: int                 # 이번 주(KST 월요일부터) 남은 생성 횟수


class BigPicture(BaseModel):
    source: Literal["generated", "mega"]   # generated = 주간 생성분, mega = 첫 생성 전(메가 서사 + 세계관 브리핑 전제)
    strands: list[Strand]
    premises: Premises
    generated_at: str | None
    week: str | None                  # 'YYYY-Www'
    mega: list[MegaItem]
    worldview: StoredWorldview | None
    as_of: str | None
    inputs: BigPictureInputs
    inputs_as_of: str | None          # 근거 중 가장 늦은 시각(UTC) — 머리 '기준'
    stale_days: int | None            # 기준 시각 경과일(생성분) · 세계관 브리핑 경과일(첫 생성 전)
    new_versions_since: int | None    # 생성(또는 브리핑) 뒤 새 내러티브 버전 수
    rebuild: RebuildState


class RebuildResult(BaseModel):
    status: Literal["ok", "skipped", "cooldown", "budget", "unavailable", "failed", "empty", "off"]
    reason: str | None = None
    retry_at: str | None = None
    key: str | None = None
    strands: int | None = None


class NarrativeChange(BaseModel):
    topic: str
    narrative_id: int
    version: int
    title: str | None
    category: str | None
    created_at: str | None
    drift_summary: str | None
    change_summary: str | None   # 서사가 어떻게 옮겨 갔나 1~2문장 (저장분 → 없으면 drift 첫 문장, 첫 버전은 null)
    versions_in_window: int
    is_first: bool           # 첫 버전 — 비교할 직전 버전이 없다
    added_count: int
    removed_count: int
    added_edges: list[dict]   # {from, to, rel, effect_direction} 최대 5
    removed_edges: list[dict]


class NarrativeChanges(BaseModel):
    days: int
    items: list[NarrativeChange]
    as_of: str | None


class RefuteDoc(BaseModel):
    doc_id: int | None
    title: str | None
    observed_at: str | None


class ContestedItem(BaseModel):
    id: int
    statement: str
    pace_layer: str
    contested_at: str | None
    refute: int
    support: int
    latest_refute: RefuteDoc | None


class Contested(BaseModel):
    items: list[ContestedItem]
    as_of: str | None


class StockNarrative(BaseModel):
    topic: str
    narrative_id: int
    title: str | None
    version: int
    created_at: str | None
    drift_summary: str | None
    edges: int
    via: str                 # edge(그 종목이 걸린 엣지를 만든 서사) | neighbor(엣지 건너편 노드가 서사 주제)


class StockNarratives(BaseModel):
    stock_code: str
    name: str | None
    kinds: list[str]         # portfolio | watch
    narratives: list[StockNarrative]
    latest_drift: str | None
    latest_at: str | None


class MyStockNarratives(BaseModel):
    stocks: list[StockNarratives]
    members: int             # 묶음 종목 수
    covered: int             # 서사가 걸린 종목 수
    as_of: str | None


class CheckpointQuestion(BaseModel):
    id: int
    text: str
    status: str
    lead_verdict: str | None
    confirm_verdict: str | None


class Falsifier(BaseModel):
    condition: str
    source: str              # knowledge | question
    about: str | None


class Beneficiary(BaseModel):
    name: str
    type: str
    via: str                 # chain(근본 원인→수혜 경로) | claim(서사의 수혜 엣지)
    stock_code: str | None


class MyStock(BaseModel):
    stock_code: str
    name: str | None
    kinds: list[str]
    edges: int


class Checkpoint(BaseModel):
    status: str              # ok | empty
    topic: str
    narrative_id: int | None = None
    title: str | None = None
    core_question: str | None = None
    question: CheckpointQuestion | None = None
    falsifiers: list[Falsifier] = []
    beneficiaries: list[Beneficiary] = []
    my_stocks: list[MyStock] = []

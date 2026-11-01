"""월드모델 읽기 전용 응답 (docs/specs/world-model.md). 전부 저장분 조회 — LLM 없음."""
from pydantic import BaseModel


class MegaItem(BaseModel):
    id: int
    name: str
    title: str | None
    narrative: str | None
    members: list[str]
    version: int
    created_at: str | None


class StoredWorldview(BaseModel):
    briefing: str | None
    created_at: str | None
    stale: bool              # 입력(지식·주간 신호)이 저장 이후 바뀜 — 갱신은 지식 화면에서만


class BigPicture(BaseModel):
    mega: list[MegaItem]
    worldview: StoredWorldview | None
    as_of: str | None


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

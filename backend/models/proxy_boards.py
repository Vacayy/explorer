"""프록시 보드 요청·응답 모델 (D-240)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["up", "down"]


class BoardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    question_id: int | None = None
    narrative_id: int | None = None
    group_id: int | None = None


class BoardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    question_id: int | None = None
    narrative_id: int | None = None
    group_id: int | None = None


class BoardSummary(BaseModel):
    id: int
    name: str
    description: str | None
    question_id: int | None
    narrative_id: int | None
    group_id: int | None
    created_at: str | None
    updated_at: str | None
    item_count: int
    in_warn_count: int                  # 주의 방향으로 움직인 지표 수(변화 기준은 지표마다 change_basis)


class Latest(BaseModel):
    value: float | None
    as_of: str | None                   # 원천 날짜(수출입은 YYYY-MM). 지금 시각이 아니다
    change: float | None                # 값과 같은 단위의 차이
    change_pct: float | None            # 수준 지표(가격·수출액)만
    change_basis: str | None            # '30일 전' | '전월' | '직전 시즌 같은 시점(7일차)' ...
    direction: Literal["up", "down", "flat"] | None
    unit: str | None


class Point(BaseModel):
    date: str
    value: float


class BoardItem(BaseModel):
    proxy_id: int
    position: int
    label: str
    adapter: str | None                 # None = 원천을 알 수 없는 기존 프록시(관측 없음)
    adapter_ref: str | None
    unit: str | None
    warn_direction: Direction | None
    rationale: str | None
    missing: bool = False               # 보드에 있으나 프록시가 지워졌다
    latest: Latest
    in_warn: bool
    series: list[Point]


class BoardDetail(BoardSummary):
    items: list[BoardItem]


class ItemAdd(BaseModel):
    """기존 프록시(proxy_id) 또는 새 정의(label·adapter·adapter_ref) 중 하나."""
    model_config = ConfigDict(extra="forbid")
    proxy_id: int | None = None
    label: str | None = Field(default=None, max_length=120)
    adapter: str | None = None
    adapter_ref: str | None = None
    unit: str | None = None
    warn_direction: Direction | None = None
    rationale: str | None = None


class ItemAdded(BaseModel):
    proxy_id: int
    position: int


class ItemOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proxy_ids: list[int]


class AdapterInfo(BaseModel):
    kind: str
    label: str
    ref_format: str
    description: str
    change_basis: str


class CatalogEntry(BaseModel):
    ref: str
    label: str
    unit: str | None


class SuggestReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=200)
    question_id: int | None = None
    narrative_id: int | None = None


class Candidate(BaseModel):
    label: str
    adapter: str
    adapter_ref: str
    unit: str | None
    warn_direction: Direction | None
    rationale: str | None
    lead_or_confirm: Literal["lead", "confirm"] | None
    source_label: str                   # 원천이 붙인 이름(검증된 ref의 실제 지표)


class NeedsSource(BaseModel):
    label: str
    adapter: str | None
    adapter_ref: str | None
    rationale: str | None
    reason: str                         # 왜 원천 없음인가 — 모델이 적은 필요 데이터 또는 검증 실패 사유


class SuggestResp(BaseModel):
    topic: str
    candidates: list[Candidate]
    needs_source: list[NeedsSource]

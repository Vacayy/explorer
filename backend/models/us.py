"""미국 종목 도시에 API 스키마 (docs/specs/us-dossier.md)."""
from typing import Any

from pydantic import BaseModel


class UsDossier(BaseModel):
    ticker: str
    name: str
    entity_id: int | None = None
    fundamentals: dict[str, Any] | None = None   # yfinance 스냅샷 (price·fwd_pe·estimates…)
    latest_transcript: dict[str, Any] | None = None  # 최근 컨콜 메타 (있으면)


class UsListItem(BaseModel):
    ticker: str
    name: str
    group_label: str | None = None
    value_stance: str | None = None    # 강|중|약 (캐시된 렌즈 판독, 없으면 None)
    trend_stance: str | None = None    # 초입|진행|성숙|훼손
    quadrant_cell: str | None = None   # 두 stance로 계산(LLM 0)
    price: float | None = None         # us_fundamentals 캐시 가격(없으면 None, fetch 안 함)


class UsGroup(BaseModel):
    label: str
    items: list[UsListItem]


class UsList(BaseModel):
    groups: list[UsGroup]


class UsMention(BaseModel):
    id: int
    source_type: str
    title: str | None = None
    url: str | None = None
    published_at: str | None = None
    excerpt: str | None = None

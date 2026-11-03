"""Market Today API 스키마 (docs/specs/market-today.md)."""
from pydantic import BaseModel


class TodaySource(BaseModel):
    ref: str
    kind: str                    # telegram | news
    publisher: str | None
    title: str | None
    url: str | None
    doc_id: int | None
    published_at: str | None
    echo: int                    # 같은 얘기를 올린 출처 수


class TodayTopic(BaseModel):
    title: str
    body: str
    tags: list[str]
    continuing: bool             # 직전 회차 화두가 이어지는가
    echo: int                    # 이 화두를 다룬 출처 수(묶음 포함) — 정렬 기준
    refs: list[str]
    sources: list[TodaySource]


class TodaySlot(BaseModel):
    slot: str                    # 1000 | 1300 | 1540
    label: str                   # 10:00 …
    created_at: str
    topics: int


class IndexAt(BaseModel):
    value: float
    change_pct: float | None
    at: str                      # HH:MM KST — 값이 찍힌 시각


class TodayMarket(BaseModel):
    """회차 시점 시장 상태 — 화두가 돌 때 시장이 어땠는지"""
    kospi: IndexAt | None = None
    kosdaq: IndexAt | None = None
    path: list[tuple[str, float]] = []   # 코스피 5분 경로 [HH:MM, 값] — 장중 타임라인 선


class TodayCurrent(BaseModel):
    slot: str
    label: str
    window_start: str
    window_end: str
    created_at: str
    doc_count: int
    telegram: int
    news: int
    market: TodayMarket | None
    topics: list[TodayTopic]


class MarketToday(BaseModel):
    trade_date: str | None
    slots: list[TodaySlot]
    current: TodayCurrent | None
    next_slot: str | None        # 오늘 남은 다음 회차(KST) — 주말·장 마감 뒤면 None

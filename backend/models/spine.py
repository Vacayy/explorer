"""spine 읽기 API 응답 스키마 (docs/specs/frontend-plan.md Phase B)."""
from pydantic import BaseModel


class EntityTag(BaseModel):
    entity_id: int
    type: str          # company | sector | theme
    name: str
    aliases: str | None  # company면 종목코드 (칩 클릭 → 필터/디테일 이동용)
    link_type: str     # stock | industry | topic | mention
    confidence: float | None


class FeedDocument(BaseModel):
    id: int
    source_type: str
    title: str
    url: str
    published_at: str
    summary: str | None
    enrich_model: str | None   # keyword | LLM 모델명 (epistemic 표시용)
    entities: list[EntityTag]


class FeedResponse(BaseModel):
    items: list[FeedDocument]
    total: int
    page: int
    size: int
    as_of: str


class SignalItem(BaseModel):
    id: int
    signal_type: str
    entity_id: int
    entity_name: str
    stock_code: str | None
    date: str
    payload: dict
    interpretation: str | None
    interpretation_model: str | None


class SignalsResponse(BaseModel):
    items: list[SignalItem]
    as_of: str


class CalendarEvent(BaseModel):
    id: int
    stock_code: str | None
    corp_name: str | None
    event_type: str
    event_date: str
    title: str
    in_watchlist: bool


class WatchlistUpdate(BaseModel):
    kind: str                  # document | signal
    stock_code: str
    corp_name: str
    occurred_at: str
    title: str
    url: str | None
    source_type: str | None    # document일 때
    signal_type: str | None    # signal일 때


class HomeResponse(BaseModel):
    calendar: list[CalendarEvent]
    watchlist_updates: list[WatchlistUpdate]
    market_highlights: list[SignalItem]
    watchlist_empty: bool
    as_of: str

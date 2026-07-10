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
    channel: str | None        # 출처 채널/블로그 이름 (예: cahier_de_market, 메르의 블로그)
    content: str | None        # 전문 (markdown) — 카드 펼침용
    images: list[str]          # /media 상대경로
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
    entity_type: str = "company"   # company | sector | theme (팔로우 엔티티)
    entity_id: int | None = None
    doc_id: int | None = None      # document일 때 — 내부 디테일(/doc/:id) 링크용
    stock_code: str | None
    corp_name: str             # 표시명 (엔티티명)
    occurred_at: str
    title: str
    url: str | None
    source_type: str | None    # document일 때
    signal_type: str | None    # signal일 때


class HomeFollow(BaseModel):
    entity_id: int
    type: str
    name: str


class BriefItem(BaseModel):
    """'기계가 먼저 말하는 3줄' — 판단이 아니라 변화 감지만 (epistemic 규율)."""
    kind: str            # insight(가설 스타일) | action | signal
    text: str
    to: str              # 프론트 라우트 (근거로 1클릭)


class HomeResponse(BaseModel):
    briefing: list[BriefItem]
    calendar: list[CalendarEvent]
    follows: list[HomeFollow]
    watchlist_updates: list[WatchlistUpdate]
    market_highlights: list[SignalItem]
    watchlist_empty: bool
    as_of: str

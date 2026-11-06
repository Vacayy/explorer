"""spine 읽기 API 응답 스키마 (docs/private/specs/frontend-plan.md Phase B)."""
from typing import Literal

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
    channel_kind: str | None = None   # telegram | blog — 소스 도시에(/source) 링크용
    channel_key: str | None = None    # channel_name | blog url
    content: str | None        # 전문 (markdown) — 카드 펼침용
    images: list[str]          # /media 상대경로
    enrich_model: str | None   # keyword | LLM 모델명 (epistemic 표시용)
    digest_status: str | None = None
    digest_error: str | None = None
    video_digest: str | None = None
    transcript: str | None = None
    entities: list[EntityTag]


class FeedFacetEntity(BaseModel):
    name: str
    link_type: str           # stock | industry | topic
    aliases: str | None      # 종목이면 종목코드
    count: int


class FeedFacets(BaseModel):
    """검색 결과 전체(페이지 아님)의 소스별 건수와 자주 같이 나온 종목·테마 — 검색어가 있을 때만."""
    sources: dict[str, int]
    entities: list[FeedFacetEntity]


class FeedResponse(BaseModel):
    items: list[FeedDocument]
    total: int
    page: int
    size: int
    as_of: str
    facets: FeedFacets | None = None


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


class AiActivityItem(BaseModel):
    """'AI가 최근 만든 것' 한 줄 — 상단 바 `layout/AiOutputs`가 피드 Explorer 타임라인과 합쳐 쓴다(D-325)."""
    type: Literal["narrative", "mega", "report", "scenario", "digest", "youtube_digest"]
    title: str
    topic: str
    code: str | None = None          # digest면 종목코드(analyze 링크용)
    question_id: int | None = None   # scenario가 질문에 묶였으면(D-070) — /question/:id 링크용
    doc_id: int | None = None        # 유튜브 AI 정리본의 /doc/:id 링크용
    created_at: str                  # UTC 'YYYY-MM-DD HH:MM:SS'


class HomeResponse(BaseModel):
    briefing: list[BriefItem]
    calendar: list[CalendarEvent]
    follows: list[HomeFollow]
    watchlist_updates: list[WatchlistUpdate]
    market_highlights: list[SignalItem]
    watchlist_empty: bool
    as_of: str


class KrBreadth(BaseModel):
    """국내 시장 폭(D-321) — 홈 기상도의 상승·하락 색 비율. 자료가 없으면 응답 전체가 null."""
    trade_date: str
    prev_date: str
    up: int
    down: int
    flat: int
    up_ratio: float   # up / (up + down)

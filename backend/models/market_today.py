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


class TopicNarrative(BaseModel):
    """화두에 걸린 내러티브(ia-redesign §9.1) — 주제 기준 연결, 버전·날짜는 지금 살아 있는 버전"""
    topic: str
    narrative_id: int
    version: int
    created_at: str | None
    rule: int                    # 1 태그 일치 | 2 자료 겹침 + 태그 부분 일치 | 3 자료 겹침
    doc_overlap: int             # 그 주제에 연결된 출처 문서 수(주제 이름 기준)


class TodayTopic(BaseModel):
    title: str
    body: str
    tags: list[str]
    continuing: bool             # 직전 회차 화두가 이어지는가
    echo: int                    # 이 화두를 다룬 출처 수(묶음 포함) — 정렬 기준
    refs: list[str]
    sources: list[TodaySource]
    narratives: list[TopicNarrative]   # 연결 없음·계산 전이면 []


class TodaySlot(BaseModel):
    slot: str                    # 0930 | 1130 | 1500 | 1600(마감 정리) · 옛 1000 | 1300 | 1540
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
    links_ready: bool            # 내러티브 연결을 계산했는가 — 아니면 칩 줄을 그리지 않는다
    topics: list[TodayTopic]


class MarketToday(BaseModel):
    trade_date: str | None       # 보는 날(KST). 기본은 오늘 — 자정에 넘어가 회차 전이면 slots 비어 있음
    slots: list[TodaySlot]
    current: TodayCurrent | None
    next_slot: str | None        # 오늘 남은 다음 회차(KST) — 주말·장 마감 뒤면 None
    prev_date: str | None = None  # 이 날보다 앞에서 회차가 있는 가장 가까운 날 — '‹' 이동
    next_date: str | None = None  # 뒤로 회차가 있는 날(없고 오늘보다 앞이면 오늘)


# ---------- 화두 → 내러티브 연결 (ia-redesign §9) ----------

class TimelineCell(BaseModel):
    slot: str
    label: str
    state: str                   # linked 연결 | unlinked 연결 없음 | scheduled 예정 | absent 회차 없음
    wrap: bool                   # 16:00 마감 정리


class TimelineDay(BaseModel):
    trade_date: str
    cells: list[TimelineCell]


class TimelineItem(BaseModel):
    mt_id: int
    trade_date: str
    slot: str
    label: str
    title: str
    rule: int
    doc_overlap: int
    wrap: bool


class NarrativeMarketToday(BaseModel):
    """내러티브 상세 '장중 화두 타임라인'"""
    topic: str
    narrative_id: int
    collected_since: str | None  # Market Today 수집 시작 거래일
    days: list[TimelineDay]      # 최근 2일(최신 먼저)
    items: list[TimelineItem]    # 연결된 화두(최신 먼저, 최대 30)
    week_topics: int             # 이번 주(월요일부터) 연결 화두 수 — 마감 정리 제외
    week_sessions: int           # 이번 주 연결 회차 수 — 마감 정리 제외
    boost: bool                  # 다음 갱신 앞당김(이번 주 3회차 이상 + 갱신 3일 경과)


class CandidateSession(BaseModel):
    mt_id: int
    trade_date: str
    slot: str
    label: str


class MergeTarget(BaseModel):
    topic: str
    overlap: int                 # 후보 출처와 그 서사 근거가 겹친 문서 수
    narrative_id: int
    version: int
    created_at: str | None


class NarrativeCandidate(BaseModel):
    tag: str                     # 대표 태그(정규화) — approve·dismiss 경로 키
    name: str
    status: str                  # pending 후보 | approved 승인(첫 버전 대기) | watching 관찰 중
    first_seen: str
    last_seen: str
    days: int
    sessions: int
    sources: int
    tags: list[str]
    session_list: list[CandidateSession]
    titles: list[str]
    linked: list[str]            # 이 묶음 화두가 칩으로 걸린 서사
    merge_into: MergeTarget | None
    narrative_topic: str | None
    attempt: str | None          # 승인 뒤 첫 버전 시도 결과(fresh·empty·not_found…)


class NarrativeCandidates(BaseModel):
    items: list[NarrativeCandidate]


class CandidateAction(BaseModel):
    tag: str
    status: str                  # approved | dismissed
    mode: str | None             # new 새 서사 | merge 합치기
    narrative_topic: str | None
    dismissed_until: str | None

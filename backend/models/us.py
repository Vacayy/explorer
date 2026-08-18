"""미국 종목 도시에 API 스키마 (docs/specs/us-dossier.md)."""
from typing import Any

from pydantic import BaseModel, Field


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


class UsMoverItem(BaseModel):
    rank: int
    ticker: str
    name: str
    close: float | None = None
    volume: float | None = None
    dollar_volume: float | None = None   # close × volume (USD)
    exchange: str | None = None          # NASDAQ | NYSE | AMEX …
    is_adr: bool = False


class UsMoversResponse(BaseModel):
    status: str                          # ok | stale | error (FE가 정상/경고/에러 구분)
    source: str
    fetched_at: str | None = None
    error: str | None = None             # stale·error 사유 (스키마 변경 등)
    items: list[UsMoverItem] = []


# ── 어젯밤 미국장 브리핑 (docs/specs/us-briefing.md) ─────────────────────────

class UsHeadline(BaseModel):
    title: str
    publisher: str | None = None
    published_at: str | None = None
    url: str | None = None
    summary: str | None = None


class UsMoverBrief(BaseModel):
    rank: int
    ticker: str
    name: str
    dollar_volume: float | None = None
    change_pct: float | None = None
    sector: str | None = None
    industry: str | None = None
    cluster: str                          # KR 섹터 라벨
    is_adr: bool = False
    is_new: bool = False                  # 직전 스냅샷 대비 신규 진입
    coverage: str                         # covered | uncovered
    entity_id: int | None = None
    mentions_3d: int = 0
    narrative: str | None = None          # 걸린 최신 내러티브 제목
    flags: list[str] = []                 # 개별 이슈 사유 (급등 +18% · 그룹 역행 · 신규 진입)
    headlines: list[UsHeadline] = []      # US 원천 헤드라인 (개별 '왜', D-097)


class UsCluster(BaseModel):
    label: str
    n: int
    dollar_volume: float
    share_pct: float                      # 상위20 거래대금 합 대비 비중
    median_change: float
    has_new: bool = False
    tickers: list[str] = []


class UsBriefingSynthesis(BaseModel):
    """4섹션 종합 (D-112). 구 스키마(`mood` 단일)는 파이프라인이 issues로 승계한다."""
    index_summary: str = ""      # ① 지수 마감 — 어디서 어떻게 끝났나
    drivers: str = ""            # ② 시장을 움직인 요인 — 매크로 × 담론
    issues: str = ""             # ③ 거래대금 기반 이슈 (구 mood)
    flow: str = ""               # ④ 시계열 흐름 — 연속인가 단절인가
    study_candidates: list[str] = []
    share_candidates: list[str] = []


class UsIndexMove(BaseModel):
    name: str
    close: float
    change_pct: float


class UsIndexBlock(BaseModel):
    as_of: str | None = None     # 거래대금 기준일과 다를 수 있다 — 화면이 날짜를 밝힌다
    items: list[UsIndexMove] = []


class UsMacroItem(BaseModel):
    name: str
    value: float
    change_pct: float
    group: str | None = None


class UsMacroSignal(BaseModel):
    as_of: str | None = None
    signal: str | None = None     # green | yellow | red
    headline: str | None = None


class UsMacroBlock(BaseModel):
    as_of: str | None = None
    items: list[UsMacroItem] = []
    lookback: str | None = None   # 변화율 비교 기준 (D-101과 동일 산출)
    signal: UsMacroSignal | None = None
    degraded: list[str] = []


class UsFlowPoint(BaseModel):
    date: str
    share_pct: float


class UsFlowSector(BaseModel):
    label: str
    series: list[UsFlowPoint] = []


class UsFlowBlock(BaseModel):
    dates: list[str] = []
    sectors: list[UsFlowSector] = []


class UsBriefingListItem(BaseModel):
    trade_date: str
    model: str | None = None
    created_at: str | None = None


class UsMarketTheme(BaseModel):
    name: str
    count: int                            # 그날 문서 수


class UsMarketDoc(BaseModel):
    id: int
    source_type: str
    title: str | None = None
    published_at: str | None = None
    excerpt: str | None = None


class UsBriefing(BaseModel):
    status: str                           # ok | stale | partial | error
    trade_date: str | None = None
    fetched_at: str | None = None
    error: str | None = None
    stale_days: int | None = None         # 스냅샷 경과일(KST) — '어젯밤'을 자처하는데 며칠 묵었나 (D-112)
    clusters: list[UsCluster] = []
    idiosyncratic: list[UsMoverBrief] = []
    movers: list[UsMoverBrief] = []
    market_themes: list[UsMarketTheme] = []   # 그날 지배 테마(왜·무슨 얘기)
    market_docs: list[UsMarketDoc] = []       # 시장구조 코멘터리 문서
    indices: UsIndexBlock = Field(default_factory=UsIndexBlock)   # ① (D-112)
    macro: UsMacroBlock = Field(default_factory=UsMacroBlock)     # ② (D-112)
    flow: UsFlowBlock = Field(default_factory=UsFlowBlock)        # ④ (D-112)
    synthesis: UsBriefingSynthesis | None = None   # None=LLM 미가용(스켈레톤만)


class UsMention(BaseModel):
    id: int
    source_type: str
    title: str | None = None
    url: str | None = None
    published_at: str | None = None
    excerpt: str | None = None


class UsEdge(BaseModel):
    src: str
    dst: str
    rel_type: str                 # CAUSES | BENEFITS_FROM
    direction: str | None = None  # positive | negative | mixed
    confidence: float | None = None
    mechanism: str | None = None
    self_is_src: bool             # 이 종목이 원인(True)인가 결과(False)인가


class UsNarrativeRef(BaseModel):
    id: int
    topic: str
    title: str | None = None


class UsWorldModel(BaseModel):
    entity_id: int | None = None
    edges: list[UsEdge]
    narratives: list[UsNarrativeRef]

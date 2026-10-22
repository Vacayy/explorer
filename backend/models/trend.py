"""가파른 추세 종목 응답 (pipeline/trend_leaders)."""
from pydantic import BaseModel


class TrendEvidence(BaseModel):
    """조건별 실제 값 + 60일 회귀선(차트는 GET /{code}/chart)"""
    close: float
    ma20: float
    ma60: float
    ma60_prev: float          # 20거래일 전 MA60
    plus_di: float
    minus_di: float
    fit_start: float          # 60거래일 log 회귀선의 시작·끝(가격)
    fit_end: float


class TrendEvent(BaseModel):
    """52주 신고가 돌파(high52) · 매물대 돌파 후 지지(vp_retest)"""
    stock_code: str
    name: str
    sector: str | None
    close: float
    kind: str
    date: str                 # 돌파일
    level: float
    held: bool                # 오늘 종가가 아직 돌파선 위
    detail: str


class TrendHigh52(BaseModel):
    """52주 신고가 단계 — breakout(최근 5거래일 전고점 돌파) · retest(60거래일 안 돌파 → 돌파선 근처 지지 → 재반등)"""
    kind: str
    date: str                 # 돌파일
    level: float              # 돌파선(직전 250거래일 최고가)
    touch_date: str | None = None
    touch_low: float | None = None
    detail: str


class TrendChart(BaseModel):
    """근거 창 차트 ≈ 2년 — 종가·MA20·MA60·52주 고점선(그날의 직전 250거래일 최고가)"""
    stock_code: str
    dates: list[str]
    closes: list[float]
    ma20: list[float | None]
    ma60: list[float | None]
    high52: list[float | None]


class TrendLeader(BaseModel):
    stock_code: str
    name: str
    sector: str | None
    market_cap: float | None
    close: float
    ret_20: float
    ret_60: float
    r2: float
    adx: float
    gap_ma20: float
    score: float
    new: bool
    events: list[str] = []
    high52: TrendHigh52 | None = None
    evidence: TrendEvidence
    spark: list[float]


class TrendLeadersResponse(BaseModel):
    as_of: str | None
    computed_from: str | None = None   # 계산에 쓴 시세의 최신 수집 시각(UTC) — 16:35·20:20 재수집 구분
    criteria: str
    universe: int
    passed: int = 0
    items: list[TrendLeader]
    events: list[TrendEvent] = []

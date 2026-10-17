"""가파른 추세 종목 응답 (pipeline/trend_leaders)."""
from pydantic import BaseModel


class TrendEvidence(BaseModel):
    """조건별 실제 값 + 차트 재료(최근 120거래일)"""
    close: float
    ma20: float
    ma60: float
    ma60_prev: float          # 20거래일 전 MA60
    plus_di: float
    minus_di: float
    fit_start: float          # 60거래일 log 회귀선의 시작·끝(가격)
    fit_end: float
    dates: list[str]
    closes: list[float]
    ma20_series: list[float | None]
    ma60_series: list[float | None]


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

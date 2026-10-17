"""대만 월매출 응답 (pipeline/tw_revenue). 금액 단위는 천 TWD."""
from pydantic import BaseModel


class TwRevenuePoint(BaseModel):
    ym: str
    revenue: float | None
    yoy_pct: float | None


class TwRevenueItem(BaseModel):
    code: str
    name: str
    layer: str
    role: str
    market: str | None
    ym: str | None                 # 이 회사의 최신 공시 월
    revenue: float | None
    yoy_pct: float | None
    mom_pct: float | None
    yoy_3m: float | None           # 최근 3개월 합의 전년 대비
    lagging: bool                  # 전체 최신 월보다 공시가 늦다(1~10일 사이 미공시)
    note: str | None               # 회사가 단 증감 사유
    series: list[TwRevenuePoint]


class TwLayer(BaseModel):
    key: str
    label: str


class TwRevenueResponse(BaseModel):
    as_of: str | None              # 가장 최근 공시 월
    fetched_at: str | None         # 마지막 수집(UTC)
    reported: int                  # as_of 월을 공시한 회사 수
    total: int
    layers: list[TwLayer]
    items: list[TwRevenueItem]


class TwLinkEvidence(BaseModel):
    best_lag: int | None           # 대만이 몇 분기 앞설 때 가장 잘 맞나
    n: int                         # 짝지은 분기 수
    corr: float | None             # 분기 YoY 상관
    same_dir: float | None         # YoY 부호가 같은 비율


class TwLinkTw(BaseModel):
    code: str
    name: str


class TwLinkYoy(BaseModel):
    ym: str
    yoy: float


class TwLink(BaseModel):
    kr_code: str
    kr_name: str
    relation: str                  # peer | demand | capex
    confidence: str                # 사업 근거 확신도 상 | 중 | 중하
    reason: str
    tw: list[TwLinkTw]
    ym: str | None                 # 대만 합계의 최신 월
    yoy: float | None
    yoy_3m: float | None
    yoy_3m_prev: float | None      # 3개월 전의 3개월 YoY
    state: str | None              # 가속 | 둔화 | 전환↑ | 전환↓ | 유지
    series: list[TwLinkYoy]
    evidence: TwLinkEvidence


class TwLinksResponse(BaseModel):
    as_of: str | None
    items: list[TwLink]

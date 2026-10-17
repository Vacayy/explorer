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

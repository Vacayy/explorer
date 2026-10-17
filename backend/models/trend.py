"""가파른 추세 종목 응답 (pipeline/trend_leaders)."""
from pydantic import BaseModel


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
    spark: list[float]


class TrendLeadersResponse(BaseModel):
    as_of: str | None
    criteria: str
    universe: int
    passed: int = 0
    items: list[TrendLeader]

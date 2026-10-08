"""포트폴리오 원장 스키마 (docs/specs/portfolio-ledger.md, D-212). 응답 모델에는 원화 금액·수량 필드를 두지 않는다."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: Literal["buy", "sell", "deposit", "withdraw"]
    stock_code: str | None = Field(default=None, pattern=r"^[0-9A-Z]{6}$")
    amount: float = Field(gt=0)                     # 원화 — 저장만, 응답에 싣지 않음
    price: float | None = Field(default=None, gt=0)
    fund_shortfall: bool = True
    note: str = Field(default="", max_length=500)


class Holding(BaseModel):
    code: str
    name: str
    weight_pct: float | None
    return_pct: float | None
    day_change_pct: float | None
    avg_price: float
    last_close: float | None
    last_date: str | None
    entry_date: str
    price_source: Literal["live", "close"] = "close"   # live = 장중 시세(30분 갱신)
    quoted_at: str | None = None


class PortfolioSummary(BaseModel):
    as_of: str | None
    total_return_pct: float | None
    day_return_pct: float | None
    cash_weight_pct: float | None
    holdings: list[Holding]
    quoted_at: str | None = None                       # 장중 시세 시각(없으면 종가 기준)


class HistoryPoint(BaseModel):
    date: str
    cum_return_pct: float
    day_return_pct: float


class TransactionItem(BaseModel):
    id: int
    trade_date: str
    kind: str
    stock_code: str | None
    name: str | None
    price: float | None


class ExposureDriver(BaseModel):
    key: str
    name: str
    type: str
    exposure_pct: float          # 이 변수에 연결된 보유 종목 비중 합
    holdings: list[str]
    sources: list[str]           # graph | comention | chain
    direction: str | None        # '+' 수혜 · '−' 부담 · '+−' 엇갈림 (그래프 출처만)
    confidence: float | None
    hops: int | None


class Exposure(BaseModel):
    drivers: list[ExposureDriver]
    coverage: dict[str, dict]
    held: list[str]


class PortfolioEvent(BaseModel):
    date: str
    kind: str                    # ir | earnings_notice | agm | earnings_est | report_deadline | us_earnings
    title: str
    code: str | None
    name: str | None
    estimated: bool
    url: str | None
    basis: str | None


class FlowDay(BaseModel):
    date: str
    n: int
    pos: int
    neg: int


class HoldingFlow(BaseModel):
    code: str
    name: str
    series: list[FlowDay]
    today: int
    avg7: float
    surge: bool
    tone_shift: bool
    neg_today_pct: int | None
    neg_prev_pct: int
    digest: dict | None


class ThesisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    why: str = Field(min_length=5, max_length=1000)          # 왜 샀나
    falsifier: str = Field(default="", max_length=1000)      # 무엇이면 틀린가

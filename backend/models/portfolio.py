"""포트폴리오 원장 스키마 (docs/specs/portfolio-ledger.md, D-212). 응답 모델에는 원화 금액·수량 필드를 두지 않는다."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: Literal["buy", "sell", "deposit", "withdraw"]
    stock_code: str | None = Field(default=None, pattern=r"^[0-9A-Z]{6}$")
    amount: float | None = Field(default=None, gt=0)  # 원화 — 저장만, 응답에 싣지 않음. sell_all이면 서버가 계산
    price: float | None = Field(default=None, gt=0)
    fund_shortfall: bool = True
    sell_all: bool = False                           # 매도 전량 — 그날까지의 보유 수량 × 체결가(화면은 수량을 모른다)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def amount_or_all(self):
        if self.sell_all and self.kind != "sell":
            raise ValueError("전량은 매도에서만 고를 수 있습니다.")
        if not self.sell_all and self.amount is None:
            raise ValueError("금액을 입력하세요.")
        return self


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
    entry_weight_pct: float | None = None             # 처음 연 매수의 그 시점 계좌 대비 비중(%)


class ClosedTrade(BaseModel):
    """매도 한 건의 실현 결과 — 비율·가격만(D-212 프라이버시)."""
    code: str
    name: str
    entry_date: str
    sell_date: str
    avg_price: float
    sell_price: float
    return_pct: float | None
    holding_days: int | None
    full: bool                                         # 이 매도로 전량 청산했는가


class PortfolioSummary(BaseModel):
    as_of: str | None
    total_return_pct: float | None
    day_return_pct: float | None
    cash_weight_pct: float | None
    holdings: list[Holding]
    quoted_at: str | None = None                       # 장중 시세 시각(없으면 종가 기준)
    realized_pct: float | None = None                  # 실현 손익 ÷ 원금(순입금) × 100
    unrealized_pct: float | None = None                # 미실현 손익 ÷ 원금 × 100
    closed: list[ClosedTrade] = []                     # 최근 매도부터


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


class PrincipleRule(BaseModel):
    """운용 원칙의 수치 규칙 하나(D-227) — 유형·범위 검증은 pipeline.portfolio_principles.validate."""
    type: str
    params: dict[str, float]
    summary: str | None = None


class PrincipleParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=3, max_length=20000)


class PrincipleParse(BaseModel):
    rules: list[PrincipleRule]
    unparsed: list[str]                                # 수치로 풀 수 없어 감시하지 못하는 문장


class PrincipleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=3, max_length=20000)
    rules: list[PrincipleRule] = Field(default=[], max_length=20)
    notes: list[str] = Field(default=[], max_length=60)   # 확인 화면의 '대화에서 참고하는 원칙' 목록


class Principle(BaseModel):
    id: int
    text: str
    created_at: str
    rules: list[PrincipleRule]
    notes: list[str] = []


class PrincipleText(BaseModel):
    """원문만 고친다 — 확인된 점검 규칙은 그대로(모델 재호출 없음)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=3, max_length=20000)

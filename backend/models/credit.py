"""회사채 스프레드 응답 모델 (D-230)."""
from pydantic import BaseModel


class CreditGroup(BaseModel):
    key: str
    label: str


class CreditRow(BaseModel):
    ticker: str
    name: str
    group: str
    bond: str | None
    rating: str | None
    hy: bool
    source: str | None                 # TRACE | 유럽 거래소
    ytm: float | None
    treasury: float | None
    spread_bp: int | None
    chg_1m: int | None
    chg_3m: int | None
    chg_1y: int | None
    pd_pct: float | None               # 5년 누적 부도확률(위험중립 근사, 회수율 40%)
    last_date: str | None


class CreditTable(BaseModel):
    configured: bool                   # 로컬 데이터 원천 어댑터 유무
    as_of: str | None
    groups: list[CreditGroup]
    rows: list[CreditRow]


class CreditHistory(BaseModel):
    tickers: list[str]
    points: list[dict]                 # {date, treasury, <티커>_ytm, <티커>_spread}

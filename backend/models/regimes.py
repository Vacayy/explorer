from typing import Literal
from pydantic import BaseModel


class RegimePhase(BaseModel):
    kind: Literal['bull', 'bear']
    start: str
    end: str
    start_close: float
    end_close: float
    change_pct: float
    days: int
    confirm_date: str | None
    confirm_lag_days: int | None
    provisional: bool


class RegimeCorrection(BaseModel):
    start: str
    trough: str
    end: str | None
    drawdown_pct: float
    near_threshold: bool


class RegimeTrend(BaseModel):
    state: Literal['up', 'down']
    start: str
    end: str


class RegimeRecession(BaseModel):
    start: str
    end: str
    open: bool = False


class RegimeCurrent(BaseModel):
    kind: Literal['bull', 'bear']
    start: str
    close: float
    from_peak_pct: float
    from_trough_pct: float
    trend: Literal['up', 'down'] | None


class RegimesResponse(BaseModel):
    as_of: str | None
    first_date: str | None
    fetched_at: str | None
    params: dict
    index: dict
    phases: list[RegimePhase]
    corrections: list[RegimeCorrection]
    trend: list[RegimeTrend]
    recessions: list[RegimeRecession]
    series: list[tuple[str, float]]
    current: RegimeCurrent | None


class BrkPoint(BaseModel):
    date: str
    brk_pct: float
    bench_pct: float
    rs: float


class BrkRolling(BaseModel):
    date: str
    brk_12m: float
    bench_12m: float
    excess_12m: float
    beta_36m: float | None
    beta_adj_12m: float | None


class BrkPhase(BaseModel):
    kind: Literal['bull', 'bear']
    start: str
    end: str
    provisional: bool
    clipped_start: str | None
    spx_change_pct: float
    confirm_date: str | None
    confirm_lag_days: int | None
    brk_pct: float
    bench_pct: float
    excess_pct: float
    beta: float | None
    beta_adj_pct: float | None


class BrkSummary(BaseModel):
    n: int
    brk_wins: int
    median_excess_pct: float | None
    beta_adj_wins: int
    beta_adj_n: int


class RegimeBand(BaseModel):
    kind: Literal['bear', 'recession']
    start: str
    end: str
    provisional: bool


class BrkBench(BaseModel):
    key: str
    ticker: str
    label: str
    dividends: bool
    first_date: str | None


class BrkResponse(BaseModel):
    bench: BrkBench
    brk_first_date: str | None
    range: str
    as_of: str | None
    start: str | None
    points: list[BrkPoint]
    rolling: list[BrkRolling]
    phases: list[BrkPhase]
    summary: dict[str, BrkSummary]
    bands: list[RegimeBand]


class RegimeCollectResult(BaseModel):
    key: str
    status: Literal['ok', 'skip', 'error']
    rows: int
    period: str | None = None
    error: str | None = None


class RegimeCollectResponse(BaseModel):
    results: list[RegimeCollectResult]
    collected_at: str

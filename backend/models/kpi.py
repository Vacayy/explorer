"""국내 종목 핵심 지표(도시에 머리 지표 띠) API 스키마 — routers/kpi.py."""
from pydantic import BaseModel


class FwdEstimate(BaseModel):
    fiscal_year: str
    per: float | None = None
    eps: float | None = None


class KpiData(BaseModel):
    stock_code: str
    latest_year: int | None = None          # 영업이익률·ROE·자체 계산 PER/PBR의 DART 사업보고서 연도
    close: float | None = None
    price_change_pct: float | None = None
    price_date: str | None = None           # 종가·시가총액 기준일(stock_prices)
    market_cap: float | None = None
    per: float | None = None
    pbr: float | None = None
    fund_date: str | None = None            # PER·PBR 저장값 기준일(fundamentals). 자체 계산이면 그 값은 *_calc
    per_calc: bool = False                  # True면 시가총액 ÷ 사업보고서 순이익으로 계산
    pbr_calc: bool = False                  # True면 시가총액 ÷ 사업보고서 자본총계로 계산
    op_margin: float | None = None
    op_margin_change: float | None = None
    roe: float | None = None
    roe_change: float | None = None
    revenue: float | None = None
    revenue_growth: float | None = None
    op_profit: float | None = None
    op_profit_growth: float | None = None
    net_income: float | None = None
    fwd_per: float | None = None
    fwd_per_calc: bool = False              # True면 종가 ÷ 추정 EPS로 계산
    fwd_fiscal_year: str | None = None
    fwd_eps: float | None = None
    fwd_analyst_count: int | None = None
    fwd_estimates: list[FwdEstimate] = []
    target_price_consensus: float | None = None
    consensus_source: str | None = None     # consensus.data_source (naver 등)
    consensus_fetched_at: str | None = None # 컨센서스 수집 시각(UTC, SQLite datetime)

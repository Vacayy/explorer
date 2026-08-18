"""국내시장 거래대금 상위 스키마 (D-108) — models/us.py의 국장 대응물.

미국장과 달리 LLM 종합(synthesis)이 없다 — 표 + 섹터 쏠림 + 개별 이슈까지 전부 결정적 계산.
"""
from pydantic import BaseModel


class KrMoverItem(BaseModel):
    rank: int
    stock_code: str
    name: str
    market: str | None = None            # KOSPI | KOSDAQ | KONEX
    close: int | None = None
    volume: int | None = None
    value_traded: int | None = None      # 거래대금(원)
    change_pct: float | None = None
    sector: str | None = None            # sector_map.group_name 대분류
    market_cap: int | None = None
    is_new: bool = False                 # 직전 스냅샷 대비 신규 진입
    flags: list[str] = []                # 급등/급락/그룹 역행/신규 진입


class KrCluster(BaseModel):
    label: str
    n: int
    value_traded: int
    share_pct: float
    median_change: float
    has_new: bool = False
    codes: list[str] = []
    names: list[str] = []


class KrMovers(BaseModel):
    status: str                          # ok | stale | error (FE가 정상/경고/에러 구분)
    source: str
    trade_date: str | None = None
    fetched_at: str | None = None
    error: str | None = None             # stale·error 사유 (스키마 변경 등)
    items: list[KrMoverItem] = []
    clusters: list[KrCluster] = []
    idiosyncratic: list[KrMoverItem] = []

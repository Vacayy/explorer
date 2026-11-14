"""Kalshi 예측시장 캐러셀 응답 (pipeline/kalshi.py, 홈 › 대시보드)."""
from pydantic import BaseModel


class KalshiOutcome(BaseModel):
    label: str
    ticker: str | None = None
    price: float                 # 현재 확률(최근 체결가, 0~100)
    prev: float | None = None    # Kalshi previous_price(0~100) — 저장만, 화면은 change를 쓴다
    volume: int | None = None
    change: float | None = None  # 기준 수집분(base_at) 대비 %p, 기준이 없으면 null


class KalshiEvent(BaseModel):
    event_ticker: str
    series_ticker: str
    category: str
    category_label: str
    title: str
    subtitle: str | None = None
    recent_volume: int | None = None
    close_ts: str | None = None
    url: str
    pinned: bool = False
    spark: list[tuple[str, float]] = []   # 대표 결과(outcomes[0]) 일봉 확률, 최근 60일
    outcomes: list[KalshiOutcome]


class KalshiPredictions(BaseModel):
    fetched_at: str | None
    base_at: str | None = None   # 변화 기준 수집 시각(20시간 이상 전 마지막 수집분)
    items: list[KalshiEvent]


class KalshiDetailOutcome(BaseModel):
    label: str
    ticker: str | None = None
    price: float
    volume_24h: int
    volume: int
    status: str
    result: str | None = None
    close_ts: str | None = None


class KalshiSeries(BaseModel):
    ticker: str | None = None
    label: str
    points: list[tuple[str, float]]


class KalshiDetail(BaseModel):
    event_ticker: str
    series_ticker: str
    category: str
    category_label: str
    title: str
    subtitle: str | None = None
    mutually_exclusive: bool
    close_ts: str | None = None
    rules: str | None = None
    url: str
    pinned: bool
    fetched_at: str | None = None
    range: str
    outcomes: list[KalshiDetailOutcome]
    series: list[KalshiSeries]


class KalshiPinBody(BaseModel):
    series_ticker: str
    pinned: bool


class KalshiPinResult(BaseModel):
    event_ticker: str
    pinned: bool

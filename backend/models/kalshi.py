"""Kalshi 예측시장 캐러셀 응답 (pipeline/kalshi.py, 홈 › 대시보드)."""
from pydantic import BaseModel


class KalshiOutcome(BaseModel):
    label: str
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
    outcomes: list[KalshiOutcome]


class KalshiPredictions(BaseModel):
    fetched_at: str | None
    base_at: str | None = None   # 변화 기준 수집 시각(20시간 이상 전 마지막 수집분)
    items: list[KalshiEvent]

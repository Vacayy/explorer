"""홈 › 한국 시장 · 미국 시장 ① 지수 차트 + 요약 지표 4칸 응답 모델 (ia-redesign §4.2·4.3, D-325)."""
from typing import Literal

from pydantic import BaseModel


class RangePoint(BaseModel):
    t: str        # 1d = 현지 'HH:MM', 기간 = 'YYYY-MM-DD'
    v: float


class IndexRange(BaseModel):
    key: Literal["1d", "1m", "3m", "1y"]
    base: float | None          # 기준선 — 1d는 전일 종가, 기간은 기간 시작 전 값
    points: list[RangePoint]


class IndexSession(BaseModel):
    state: Literal["pre", "open", "closed"]   # pre = 개장 전(1d는 직전 거래일 경로), open = 장중, closed = 마감·휴장
    trade_date: str | None      # 1d 경로의 현지 거래일
    last_time: str | None       # 마지막 값의 현지 시각 'HH:MM'
    last_kst: str | None        # 같은 시점의 한국 시각 'YYYY-MM-DD HH:MM'
    open: str                   # 정규장 현지 시각 'HH:MM'
    close: str


class IndexOverview(BaseModel):
    key: str                    # kospi | kosdaq | sp500 | nasdaq | dow
    name: str
    value: float | None
    change: float | None        # 전일 종가 대비
    change_pct: float | None
    prev_close: float | None    # 저장 일별 종가(market_indicators) 기준
    session: IndexSession
    ranges: list[IndexRange]


class OverviewTile(BaseModel):
    """요약 지표 한 칸 — 칸마다 기준일이 다르다(as_of). 없는 값은 null로 모양을 같게."""
    key: Literal["breadth", "indiv_net", "usdkrw", "credit", "fear_greed", "us10y", "dxy", "wti"]
    label: str
    value: float | None
    change_pct: float | None    # 직전 값 대비 %
    as_of: str | None
    series: list[float]         # 최근 20개(일별) — 시장 폭은 빈 목록
    up: int | None = None       # 시장 폭
    down: int | None = None
    flat: int | None = None
    buy: float | None = None    # 개인 매수·매도 거래대금(원)
    sell: float | None = None
    growth_20: float | None = None   # 신용융자 20영업일 변화율(비율)
    pctile: float | None = None      # 신용융자 20일 변화율의 5년 백분위(개인 투자 열기와 같은 계산)
    second: float | None = None      # 미 2년 금리(10년 칸에 병기)


class MarketOverview(BaseModel):
    market: Literal["kr", "us"]
    indices: list[IndexOverview]
    tiles: list[OverviewTile]

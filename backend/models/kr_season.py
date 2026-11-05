"""국내 실적 시즌 응답 — GET /api/spine/transcript/season/kr (pipeline.kr_season.overview, ia-redesign §4.22).

모양의 원본은 파이프라인 dict다. 키를 바꾸면 이 모델도 같은 커밋에서 바꾼다(api-contract).
미국 응답(SeasonOverview)은 그대로 두고 국내는 따로 둔다 — 국내에는 컨센서스·컨콜·섹터 요약이 없다.
"""
from typing import Literal

from pydantic import BaseModel

from models.earnings_season import SeasonRef


class KrSeasonOption(BaseModel):
    key: str
    label: str
    count: int
    is_current: bool
    partial: bool          # 전 시장 공시 수집 전 시즌이라 일부 기업만 있다


class KrCoverage(BaseModel):
    partial: bool
    full_from: str | None  # 전 시장 공시 목록 수집이 이어진 첫날


class KrWeek(BaseModel):
    n: int
    start: str
    end: str
    first: str | None
    last: str | None


class KrSeasonKpi(BaseModel):
    reported: int                  # 잠정실적 공시 회사 수
    quarterly_only: int            # 잠정실적 없이 분기보고서만 낸 회사 수(D-305)
    prev_reported: int
    week: KrWeek | None            # 지난 시즌이면 null
    outperform_n: int
    outperform_base: int
    outperform_ratio: float | None
    median_x1: float | None


class KrSeasonChanges(BaseModel):
    added_date: str | None
    added: list[str]
    settled_date: str | None
    settled: list[str]


class KrCalendarDay(BaseModel):
    date: str
    total: int                     # 잠정실적 공시 수
    quarterly: int                 # 분기보고서만 낸 회사 수(D-305)


class KrFigures(BaseModel):
    """2단계(공시 본문 파싱) 수치 — 지금은 늘 null로 온다"""
    revenue_yoy: float | None
    op_income_yoy: float | None


class KrAnnouncement(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str | None
    rcept_dt: str
    rcp_no: str
    kind: Literal["prelim", "quarterly"]       # 잠정실적 | 분기보고서만(반응일 = 보고서 접수일, D-305)
    basis: Literal["연결", "별도"] | None       # 분기보고서만 낸 곳은 null
    group: str | None
    market_cap: float | None
    r1: float | None
    x1: float | None
    r1_state: Literal["final", "same_day"] | None
    r5: float | None
    x5: float | None
    r5_state: Literal["final", "pending"] | None
    figures: KrFigures | None


class KrGroupRow(BaseModel):
    group: str
    n: int                         # 분기보고서만 낸 곳 포함
    quarterly_n: int
    median_r1: float | None
    median_x1: float | None
    up_n: int
    base_n: int
    up_ratio: float | None


class KrPending(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str
    group: str | None
    market_cap: float | None
    prev_date: str


class KrSeasonOverview(BaseModel):
    season: SeasonRef
    seasons: list[KrSeasonOption]
    deadline: str
    today: str
    prices_as_of: str | None
    disclosures_as_of: str | None
    coverage: KrCoverage
    kpi: KrSeasonKpi
    changes: KrSeasonChanges
    calendar: list[KrCalendarDay]
    announcements: list[KrAnnouncement]
    groups: list[KrGroupRow]
    pending: list[KrPending]

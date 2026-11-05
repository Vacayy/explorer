"""실적 시즌 개요 응답 — GET /api/spine/transcript/season (pipeline.earnings_chain.season_overview).

모양의 원본은 파이프라인 dict다. 키를 바꾸면 이 모델도 같은 커밋에서 바꾼다(api-contract).
"""
from typing import Literal

from pydantic import BaseModel

CoreReason = Literal["cap", "mention", "holding_chain", "dc_chain", "pinned"]


class SeasonRef(BaseModel):
    key: str
    label: str
    start: str
    is_current: bool


class SeasonWindow(BaseModel):
    """시즌별 발표 구간 — 팔로우 기업의 첫 발표일~마지막 발표일(미확정 예정일 포함). 홈 '시즌 사이' 판정용."""
    key: str
    label: str
    first: str
    last: str
    events: int
    confirmed: int


class SeasonCalendarDay(BaseModel):
    """발표 캘린더 하루 — 팔로우 기업 발표 수(핵심 몫·확정 수)와 종목."""
    date: str
    total: int
    core: int
    confirmed: int
    tickers: list[str]


class SeasonCounts(BaseModel):
    followed: int
    reported: int
    beat: int
    beat_down: int
    reversed: int
    up: int
    miss: int
    miss_up: int
    reactions: int
    reactions_final: int


class SeasonChanges(BaseModel):
    reactions: list[str]
    themes: list[str]
    expectations: list[str]
    transcripts: list[str]


class ExpectationState(BaseModel):
    d7: bool
    d1: bool
    qualitative: bool


class SeasonItem(BaseModel):
    ticker: str
    name: str | None
    sector: str
    sector_name: str
    event_date: str
    fiscal: str
    transcript_id: int | None
    reaction: Literal["interim", "final"] | None
    core: list[CoreReason]
    eps_surprise: float | None
    headline: str | None
    interpretation: str | None
    confirmed: bool
    # 발표 완료만
    d1: float | None = None
    d7: float | None = None
    d30: float | None = None
    latest: float | None = None
    latest_date: str | None = None
    follow: Literal["유지", "확대", "되돌림", "반전"] | None = None
    # 곧 발표만
    expectation: ExpectationState | None = None


class SectorTicker(BaseModel):
    ticker: str
    d1: float | None


class SeasonSectorRow(BaseModel):
    key: str
    name: str
    etf: str
    verdict: str | None
    one_line: str | None
    n_reported: int
    n_reactions: int
    tickers: list[SectorTicker]
    dc_chain: bool


class EvalCase(BaseModel):
    ticker: str
    issue: str
    verdict: Literal["hit", "underweighted", "noise", "missed"]


class SeasonEvals(BaseModel):
    hit: int
    underweighted: int
    noise: int
    missed: int
    cases: list[EvalCase]


class CoreTicker(BaseModel):
    ticker: str
    name: str | None
    reasons: list[CoreReason]


class SeasonCore(BaseModel):
    criteria: dict[str, str]
    tickers: list[CoreTicker]


class SeasonOverview(BaseModel):
    season: SeasonRef
    counts: SeasonCounts
    changes: SeasonChanges
    last_run: str | None
    windows: list[SeasonWindow]
    calendar: list[SeasonCalendarDay]
    sectors: list[SeasonSectorRow]
    top_up: list[SeasonItem]
    miss_up: list[SeasonItem]
    beat_down: list[SeasonItem]
    reversed: list[SeasonItem]
    upcoming: list[SeasonItem]
    evals: SeasonEvals
    core: SeasonCore
    reported: list[SeasonItem]

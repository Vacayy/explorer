"""관측 API 스키마 (docs/specs/observability.md)."""
from typing import Literal

from pydantic import BaseModel, Field


class UsageEvent(BaseModel):
    ts: str = Field(max_length=40)
    session: str | None = Field(default=None, max_length=64)
    type: Literal["view", "leave", "action", "open"]
    name: str = Field(min_length=1, max_length=200)
    ref: str | None = Field(default=None, max_length=200)
    entity: str | None = Field(default=None, max_length=100)
    dwell_ms: int | None = None
    section: str | None = Field(default=None, max_length=40)
    tab: str | None = Field(default=None, max_length=40)


class UsageBatch(BaseModel):
    events: list[UsageEvent] = Field(max_length=200)


class JobRow(BaseModel):
    job: str
    name: str
    n: int
    ok: int | None
    err: int | None
    part: int | None
    avg_ms: float | None = None
    last: str | None = None


class JobStreak(BaseModel):
    job: str
    name: str
    streak: int
    last: str


class JobChronic(BaseModel):
    job: str
    name: str
    runs: int


class JobTotals(BaseModel):
    runs: int
    ok: int
    err: int
    partial: int


class Jobs(BaseModel):
    total: JobTotals
    failing: list[JobRow]
    streaks: list[JobStreak]
    chronic: list[JobChronic]
    table: list[JobRow]


class ApiRow(BaseModel):
    endpoint: str
    count: int
    errors_5xx: int
    err_rate: float
    avg_ms: int | None
    p95_ms: int | None
    max_ms: int


class ApiHealth(BaseModel):
    since: str | None
    requests: int
    errors_5xx: int
    worst_errors: list[ApiRow]
    slowest: list[ApiRow]
    busiest: list[ApiRow]


class ClientErrorRow(BaseModel):
    endpoint: str
    field: str | None
    kind: str
    count: int
    last_seen: str


class Freshness(BaseModel):
    label: str
    detail: str


class CostJob(BaseModel):
    job: str
    name: str
    usd: float | None
    calls: int
    failed: int | None
    cache_pct: float | None
    share: int


class CostDay(BaseModel):
    day: str
    usd: float | None


class Costs(BaseModel):
    usd: float
    calls: int
    prev_usd: float
    change_pct: int | None
    by_job: list[CostJob]
    daily: list[CostDay]


class Screen(BaseModel):
    name: str
    visits: int
    avg_dwell_ms: float | None


class PathRow(BaseModel):
    ref: str
    name: str
    n: int


class ActionRow(BaseModel):
    name: str
    n: int


class TabRow(BaseModel):
    tab: str | None
    visits: int
    avg_dwell_ms: float | None


class SectionRow(BaseModel):
    """IA 대메뉴 단위 방문·머문 시간. section=None은 개편 전 기록(IA 위치 없음)"""
    section: str | None
    visits: int
    avg_dwell_ms: float | None
    actions: int
    tabs: list[TabRow]


class OldRouteRow(BaseModel):
    """옛 주소(리다이렉트 표) 접근 — refs = 어디서 왔는지(직전 화면) 상위"""
    name: str
    n: int
    refs: list[str]


class Usage(BaseModel):
    since: str | None
    visits: int
    sessions: int
    sections: list[SectionRow]
    screens: list[Screen]
    paths: list[PathRow]
    actions: list[ActionRow]
    dropped: list[str]
    old_routes: list[OldRouteRow]
    boards_api_calls: int


class OpenRow(BaseModel):
    name: str
    n: int
    uniq: int


class Grades(BaseModel):
    hit: int
    underweighted: int
    noise: int
    missed: int


class OpenRate(BaseModel):
    """생성 대비 열람 — generated = 기간 안에 만든 수, opened = 그중 연 것(서로 다른 대상 수)"""
    key: Literal["ai_outputs", "call", "overnight"]
    label: str
    generated: int
    opened: int


class Value(BaseModel):
    opens: list[OpenRow]
    rates: list[OpenRate]
    expectation_grades: Grades


class ObserveSummary(BaseModel):
    days: int
    generated_at: str
    jobs: Jobs
    api: ApiHealth
    client_errors: list[ClientErrorRow]
    freshness: list[Freshness]
    costs: Costs
    usage: Usage
    value: Value

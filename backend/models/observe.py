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


class Usage(BaseModel):
    since: str | None
    visits: int
    sessions: int
    screens: list[Screen]
    paths: list[PathRow]
    actions: list[ActionRow]
    dropped: list[str]


class OpenRow(BaseModel):
    name: str
    n: int
    uniq: int


class Grades(BaseModel):
    hit: int
    underweighted: int
    noise: int
    missed: int


class Value(BaseModel):
    opens: list[OpenRow]
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

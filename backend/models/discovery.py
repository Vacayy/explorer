"""User-authored discovery actions; source evidence is always resolved by the host."""
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=8, max_length=160)


class SaveStrategy(Action):
    source_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="", max_length=2000)
    date_policy: Literal["latest", "fixed"] = "latest"


class StrategyVersion(SaveStrategy):
    expected_version: int = Field(ge=1)


class StrategyRun(Action):
    version: int | None = Field(default=None, ge=1)


class RecommendationRun(Action):
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    stock_code: str | None = Field(default=None, pattern=r"^[0-9A-Z]{6}$")


class CreateCase(Action):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    question: str = Field(default="이 종목에 관심이 모이는 이유와 반대 근거를 조사해 주세요.", min_length=1, max_length=4000)
    start_research: bool = False


class SaveNote(Action):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=6000)
    assumptions: str = Field(default="", max_length=6000)
    invalidation: str = Field(default="", max_length=6000)
    watch_items: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("watch_items")
    @classmethod
    def bounded_items(cls, items):
        if any(not item.strip() or len(item) > 1000 for item in items):
            raise ValueError("확인할 질문은 각각 1~1,000자여야 합니다.")
        return [item.strip() for item in items]


class ResearchRequest(Action):
    question: str = Field(min_length=1, max_length=4000)
    as_of: date | None = None

    @field_validator("as_of")
    @classmethod
    def no_future(cls, value):
        if value and value > datetime.now(ZoneInfo("Asia/Seoul")).date():
            raise ValueError("미래 기준일로 조사할 수 없습니다.")
        return value

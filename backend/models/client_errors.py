"""화면(API 래퍼)이 보고하는 오류 — docs/specs/frontend-api-reliability.md §오류 기록."""
from typing import Literal

from pydantic import BaseModel, Field


class ClientErrorReport(BaseModel):
    endpoint: str = Field(min_length=1, max_length=300)        # 'GET /api/spine/feed/company-prices' (쿼리 제외)
    kind: Literal["schema", "http", "timeout", "network", "unknown"]
    status: int | None = None
    field: str = Field(default="", max_length=300)              # 첫 검증 실패 경로 'items.0.market_cap'
    detail: str = Field(default="", max_length=500)             # 'must have required property ...'
    issues: list[dict] = Field(default_factory=list, max_length=5)
    page: str = Field(default="", max_length=300)               # 오류가 난 화면 경로


class ClientError(BaseModel):
    signature: str
    endpoint: str
    kind: str
    status: int | None
    field: str
    detail: str
    page: str
    count: int
    first_seen: str
    last_seen: str

"""Stored source and system updates share a reading surface, not an epistemic status."""
from typing import Literal

from pydantic import BaseModel, Field
from models.spine import FeedDocument


class TimelineLink(BaseModel):
    label: str
    to: str


class TimelineItem(BaseModel):
    id: str
    kind: Literal["source", "company", "person", "transcript", "trade", "narrative", "report", "scenario"]
    title: str
    body: str = ""
    occurred_at: str
    time_label: str
    subject: str
    period: str | None = None
    evidence_count: int | None = None
    ai_generated: bool = False
    to: str
    document: FeedDocument | None = None
    links: list[TimelineLink] = Field(default_factory=list)


class TimelineResponse(BaseModel):
    items: list[TimelineItem]
    page: int
    size: int
    has_more: bool
    until: str
    as_of: str


class TimelineChannel(BaseModel):
    id: str
    name: str
    platform: Literal["telegram", "blog", "youtube", "memo", "system"]
    count: int = 0
    unread: int = 0          # read_until(없으면 '*' 기준선) 이후 게시물 수 (D-200)
    latest_at: str | None = None
    preview: str = ""


class TimelineChannelsResponse(BaseModel):
    items: list[TimelineChannel]
    total: int
    total_unread: int = 0
    until: str


class MarkReadRequest(BaseModel):
    channel: str
    read_until: str


class MarkAllReadRequest(BaseModel):
    """피드 '모두 읽음'(D-301) — platform 범위의 소스를 read_until까지 한 번에 읽음으로. all = 사람 소스 전체(Explorer 산출물 제외)"""
    platform: Literal["all", "telegram", "blog", "youtube", "memo"] = "all"
    read_until: str


class MarkAllReadResponse(BaseModel):
    platform: str
    read_until: str
    channels: int            # 이번에 읽음으로 바꾼 소스 수(안 읽은 글이 있던 소스만)
    marked: int              # 그 소스들의 안 읽은 글 수 합

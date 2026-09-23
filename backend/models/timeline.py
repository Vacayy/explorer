"""Stored source and system updates share a reading surface, not an epistemic status."""
from typing import Literal

from pydantic import BaseModel, Field
from models.spine import FeedDocument


class TimelineLink(BaseModel):
    label: str
    to: str


class TimelineItem(BaseModel):
    id: str
    kind: Literal["source", "company", "person", "transcript", "trade"]
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
    platform: Literal["telegram", "blog", "youtube", "system"]
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

"""Explicit publication projection; no private tags, jobs, errors or notes."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class PublishedAttachment(BaseModel):
    id: int
    media_type: Literal['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf']
    size: int
    url: str


class PublishedChannel(BaseModel):
    id: str
    name: str
    platform: str


class PublishedDocument(BaseModel):
    id: int
    title: str
    source_type: str
    url: str | None
    published_at: str | None
    content: str
    content_kind: Literal['stored_markdown', 'stored_text']
    attachments: list[PublishedAttachment]
    channel: PublishedChannel | None = None
    summary: str | None = None
    digest_status: str | None = None
    video_digest: str | None = None
    transcript: str | None = None


class PublicationPreview(BaseModel):
    fingerprint: str
    version: int
    document: PublishedDocument
    attachment_previews: list[str]


class PublicDocumentSummary(BaseModel):
    id: int
    title: str
    source_type: str
    published_at: str | None
    snippet: str


class PublicDocumentList(BaseModel):
    items: list[PublicDocumentSummary]
    next_cursor: str | None


class ApprovePublication(BaseModel):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: int = Field(ge=0)
    rights_basis: str = Field(min_length=1, max_length=2000)
    personal_data_excluded: Literal[True]

    @field_validator('rights_basis')
    @classmethod
    def nonempty_basis(cls, value):
        if not value.strip():
            raise ValueError('Rights basis required')
        return value.strip()


class RevokePublication(BaseModel):
    expected_version: int = Field(ge=1)


class PublicationResult(BaseModel):
    id: int
    version: int
    status: Literal['approved', 'revoked']


class PublicFeedChannel(PublishedChannel):
    count: int
    latest_at: str | None
    preview: str


class PublicFeed(BaseModel):
    channels: list[PublicFeedChannel]
    items: list[PublicDocumentSummary]
    page: int
    has_more: bool
    until: str

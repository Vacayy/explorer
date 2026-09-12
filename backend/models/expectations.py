"""Experimental evidence, draft statement, and human review contracts."""
from typing import Literal
from pydantic import BaseModel, Field


class StatementFields(BaseModel):
    speaker: str = Field(default="", max_length=100)
    attribution: Literal["direct", "reported", "unknown"] = "unknown"
    speaker_quote: str = Field(default="", max_length=1000)
    product: Literal["hbm", "dram", "nand", "memory"] = "memory"
    target: str = Field(default="메모리 산업", min_length=1, max_length=120)
    lens: Literal["business", "valuation", "psychology", "position", "flows"] = "business"
    metric: Literal["demand", "supply", "price", "margin", "qualification", "position", "other"] = "other"
    axis: Literal["level", "growth", "acceleration", "timing", "conviction", "position"] = "level"
    horizon: str = Field(default="unknown", min_length=1, max_length=120)
    basis: str = Field(default="unknown", min_length=1, max_length=200)
    direction: Literal["up", "down", "flat", "unclear"] = "unclear"
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(default="", max_length=60)
    quote: str = Field(min_length=5, max_length=4000)
    claim: str = Field(min_length=1, max_length=800)
    conditions: str = Field(default="", max_length=500)


class ReviewStatement(StatementFields):
    expected_revision: int = Field(ge=0)
    status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=3000)


class ManualStatement(StatementFields):
    doc_id: int = Field(ge=1)
    text_sha256: str = Field(min_length=64, max_length=64)


class ExtractionRequest(BaseModel):
    doc_id: int = Field(ge=1)


class JudgmentNote(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class AttributionCue(BaseModel):
    kind: Literal["self_introduction", "signature", "reported_speech"]
    text: str
    start: int
    end: int
    status: Literal["unverified"] = "unverified"


class EvidenceDocument(BaseModel):
    id: int
    source_type: str
    source_id: str
    source_url: str | None
    title: str | None
    published_at: str | None
    fetched_at: str | None
    products: list[str]
    text_kind: Literal["derived_summary", "stored_transcript", "stored_text", "empty"]
    text_field: Literal["markdown", "raw_content"]
    text_sha256: str
    text_length: int
    text: str | None = None
    source_text_available: bool
    speaker_status: Literal["unresolved"] = "unresolved"
    speaker: str | None = None
    attribution_cues: list[AttributionCue] = Field(default_factory=list)
    warnings: list[str]


class EvidencePage(BaseModel):
    items: list[EvidenceDocument]
    scanned: int
    next_before_id: int | None
    has_more: bool
    scope: str = "stored blog/telegram/youtube; lexical product candidates, not verified statements"
    experiment_version: str = "evidence-v1"


class ReadingItem(BaseModel):
    document: EvidenceDocument
    channel_name: str
    channel_key: str
    summary: str | None = None
    excerpt: str
    copies: list[int] = Field(default_factory=list)


class ReadingPage(BaseModel):
    items: list[ReadingItem]
    as_of: str
    since: str
    scanned: int
    matched: int
    duplicates: int
    truncated: bool
    latest_fetched_at: str | None = None
    source_counts: dict[str, int]
    discussion_ids: list[int]


class ReadingHistory(BaseModel):
    current: ReadingItem
    previous: list[ReadingItem]
    scanned: int
    truncated: bool
    note: str

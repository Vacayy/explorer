"""Stored-document evidence contract used by chat attachments."""
from typing import Literal
from pydantic import BaseModel, Field


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

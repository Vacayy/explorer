"""Owner-scoped bookmarks of currently approved documents."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SavedCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_id: int = Field(ge=1, strict=True)
    note: str | None = Field(default=None, max_length=2000)


class SavedNote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str | None = Field(max_length=2000)


class SavedItem(BaseModel):
    id: int
    doc_id: int
    title: str | None
    url: str | None
    available: bool
    status: Literal['available', 'changed', 'unavailable']
    current_url: str | None
    note: str | None
    created_at: str


class SavedPage(BaseModel):
    items: list[SavedItem]
    next_offset: int | None


class SavedChanged(BaseModel):
    ok: bool

from pydantic import BaseModel


class IRNoteCreate(BaseModel):
    title: str
    content: str | None = None
    note_date: str
    memo_type: str = "general"


class IRNoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    note_date: str | None = None
    memo_type: str | None = None


class IRNoteResponse(BaseModel):
    id: int
    corp_code: str
    title: str
    content: str | None = None
    note_date: str
    memo_type: str = "general"
    created_at: str
    updated_at: str

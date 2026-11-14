from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrialMessage(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=16384)

    @field_validator('content')
    @classmethod
    def bounded_content(cls, value):
        if len(value.encode('utf8')) > 16384:
            raise ValueError('Message too large')
        return value


class TrialQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=4000)
    history: list[TrialMessage] = Field(default_factory=list, max_length=4)
    search_query: str | None = Field(default=None, max_length=120)
    document_ids: list[int] = Field(default_factory=list, max_length=4)

    @field_validator('question')
    @classmethod
    def bounded_question(cls, value):
        if not value.strip() or len(value.encode('utf8')) > 12288:
            raise ValueError('Invalid question')
        return value

    @field_validator('search_query')
    @classmethod
    def valid_text(cls, value):
        if value is not None:
            value.encode('utf8')
        return value

    @field_validator('document_ids')
    @classmethod
    def valid_ids(cls, value):
        if any(not 0 < i < 2**63 for i in value) or len(set(value)) != len(value):
            raise ValueError('Invalid document selection')
        return value


class TrialSession(BaseModel):
    remaining: int
    limit: int
    csrf_token: str


class TrialCitation(BaseModel):
    id: str
    title: str
    url: str


class TrialAnswer(BaseModel):
    answer: str
    citations: list[TrialCitation]
    partial: bool
    remaining: int

"""Explicit reading intents; labels never determine the server's task."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator

StudyIntent = Literal['explain', 'critique', 'related']


class ActionSelection(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    exact: str = Field(min_length=1, max_length=18000)


class ActionAnnotation(BaseModel):
    id: int = Field(gt=0)
    revision: int = Field(gt=0)


class AnnotationActionRequest(BaseModel):
    intent: StudyIntent
    request_key: str = Field(min_length=8, max_length=100)
    selection: ActionSelection | None = None
    annotation: ActionAnnotation | None = None
    parent_id: int | None = Field(default=None, gt=0)
    retry_of: int | None = Field(default=None, gt=0)
    question: str = Field(default='', max_length=4000)
    research: Literal['auto', 'web'] = 'auto'

    @model_validator(mode='after')
    def check_target(self):
        if (self.selection is None) == (self.annotation is None):
            raise ValueError('선택 영역 또는 기존 표시 중 하나를 지정해 주세요.')
        if (self.parent_id or self.retry_of) and not self.annotation:
            raise ValueError('후속 질문과 재시도에는 기존 표시가 필요합니다.')
        if self.parent_id and (not self.question.strip() or self.retry_of):
            raise ValueError('후속 질문을 입력해 주세요. 재시도와 함께 보낼 수 없습니다.')
        return self

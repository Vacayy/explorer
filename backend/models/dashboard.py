"""홈 위젯 배치 (docs/SYSTEM.md · dashboard_layouts)."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LayoutItem(BaseModel):
    """격자 위 위젯 인스턴스 하나. x·y·w·h는 격자 칸 단위."""
    model_config = ConfigDict(extra='forbid')

    i: str = Field(min_length=1, max_length=64)        # 인스턴스 id (배치 안에서 유일)
    widget: str = Field(min_length=1, max_length=64)   # 위젯 종류 id ('market.regime')
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    w: int = Field(ge=1, strict=True)
    h: int = Field(ge=1, strict=True)
    params: dict[str, Any] = Field(default_factory=dict)


class LayoutBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[LayoutItem] = Field(max_length=100)

    @field_validator('items')
    @classmethod
    def unique_instances(cls, items: list[LayoutItem]) -> list[LayoutItem]:
        ids = [item.i for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('위젯 인스턴스 id(i)가 중복됐습니다.')
        return items


class Layout(LayoutBody):
    name: str
    updated_at: str


class LayoutSummary(BaseModel):
    name: str
    updated_at: str
    count: int



class PresetIn(LayoutBody):
    label: str = Field(min_length=1, max_length=30)
    board: str = Field(default='home-v2', pattern=r'^[a-z0-9_-]{1,40}$')


class PresetPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str | None = Field(default=None, min_length=1, max_length=30)
    items: list[LayoutItem] | None = Field(default=None, max_length=100)


class Preset(BaseModel):
    id: int
    board: str
    label: str
    items: list[LayoutItem]
    updated_at: str

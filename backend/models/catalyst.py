from pydantic import BaseModel


class CatalystCreate(BaseModel):
    stock_code: str | None = None
    event_type: str = "earnings"  # earnings|filing|contract|capex|regulation|other
    event_date: str
    title: str
    description: str | None = None


class CatalystUpdate(BaseModel):
    event_type: str | None = None
    event_date: str | None = None
    title: str | None = None
    description: str | None = None


class CatalystResponse(BaseModel):
    id: int
    stock_code: str | None
    corp_code: str | None
    corp_name: str | None
    event_type: str
    event_date: str
    title: str
    description: str | None
    created_at: str

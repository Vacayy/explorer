from pydantic import BaseModel


class FinancialRow(BaseModel):
    account_nm: str
    values: list[str | None]
    yoy: list[float | None] = []


class FinancialResponse(BaseModel):
    periods: list[str]
    rows: list[FinancialRow]
    sj_div: str
    fs_div: str
    period_type: str

"""Shared stored/collected financial response contract."""
from typing import Literal
from pydantic import BaseModel


class FinancialRow(BaseModel):
    account_nm: str
    values: list[str | None]
    yoy: list[float | None]


class FinancialResponse(BaseModel):
    periods: list[str]
    rows: list[FinancialRow]
    key_metrics: dict[str, FinancialRow]
    sj_div: Literal['IS', 'CIS', 'BS', 'CF']
    fs_div: Literal['CFS', 'OFS']
    period_type: Literal['annual', 'quarterly', 'trailing']

"""Member ledger mutation and minimal shared company contracts."""
from pydantic import BaseModel


class TransactionCreated(BaseModel):
    ok: bool
    id: int


class TransactionDeleted(BaseModel):
    ok: bool


class CompanyChoice(BaseModel):
    stock_code: str
    corp_name: str



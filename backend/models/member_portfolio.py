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



from typing import Annotated
from pydantic import Field
from models.portfolio import PrincipleCreate


class MemberPrincipleCreate(PrincipleCreate):
    notes: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=60)


class PrincipleCreated(BaseModel):
    id: int
    ok: bool


class PrincipleChanged(BaseModel):
    ok: bool

from typing import Literal


class MemberRuleCoverage(BaseModel):
    principle_id: int
    rule_index: int
    rule: str
    status: Literal['evaluated', 'partial', 'unavailable', 'not_applicable']
    reason: str | None


class MemberRuleViolation(BaseModel):
    key: str
    principle_id: int
    rule: str
    message: str


class MemberPrincipleState(BaseModel):
    as_of: str | None
    rules: int
    coverage: list[MemberRuleCoverage]
    items: list[MemberRuleViolation]
    notifications_enabled: Literal[False] = False

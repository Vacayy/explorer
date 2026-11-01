"""Public Peer read contract. Signal publication remains explicitly held."""
from datetime import date, datetime
from urllib.parse import urlsplit
from typing import Annotated, Literal
from pydantic import BaseModel, Field, model_validator

Code = Annotated[str, Field(pattern=r'^\d{6}$')]
Day = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class PeerSource(BaseModel):
    url: str
    claim: str
    verification: str
    period: str = ''
    publishedAt: str = ''


class PeerGroup(BaseModel):
    id: str
    name: str
    scope: Literal['product', 'value_chain']
    interpretation: str


class PeerCompany(BaseModel):
    code: Code
    name: str
    asOf: Day
    products: list[str]
    aliases: list[str]
    groupIds: list[str]
    caveats: list[str]
    sources: list[PeerSource]


class PeerCatalog(BaseModel):
    version: str
    asOf: Day
    groups: list[PeerGroup]
    companies: list[PeerCompany]

    @model_validator(mode='after')
    def references(self):
        ids = {group.id for group in self.groups}
        if len(ids) != len(self.groups) or len({c.code for c in self.companies}) != len(self.companies):
            raise ValueError('duplicate catalog identifier')
        if any(not set(c.groupIds) <= ids for c in self.companies):
            raise ValueError('unknown group reference')
        for company in self.companies:
            for source in company.sources:
                if urlsplit(source.url).scheme not in ('https', 'http') or not urlsplit(source.url).hostname:
                    raise ValueError('invalid evidence URL')
        return self


class PeerQualityIssue(BaseModel):
    code: Code
    date: Day
    reason: str
    sourceUrl: str


class PeerPrices(BaseModel):
    version: str
    asOf: Day
    collectedAt: datetime
    sourceUrl: str
    sourceHash: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    field: Literal['regularMarketClosingPrice']
    session: Literal['KRX_REGULAR']
    adjustmentStatus: Literal['unverified']
    dates: Annotated[list[Day], Field(min_length=1)]
    prices: dict[Code, list[Positive | None]]
    qualityIssues: list[PeerQualityIssue]
    caveats: list[str]

    @model_validator(mode='after')
    def time_series(self):
        if self.dates != sorted(set(self.dates)) or self.dates[-1] != self.asOf:
            raise ValueError('invalid date ordering/asOf')
        for day in self.dates:
            date.fromisoformat(day)
        if any(len(values) != len(self.dates) for values in self.prices.values()):
            raise ValueError('inconsistent series lengths')
        if self.collectedAt.tzinfo is None:
            raise ValueError('collection timezone required')
        return self


class PeerAttempt(BaseModel):
    at: datetime
    status: Literal['ok', 'skipped', 'error']
    asOf: Day | None = None
    error: str | None = None


class PeerRuntime(BaseModel):
    catalog: PeerCatalog
    prices: PeerPrices
    origin: Literal['collector', 'seed']
    publishedAt: datetime | None
    baselineOn: Day | None
    lastAttempt: PeerAttempt | None
    priceAgeDays: Annotated[int, Field(ge=0)]
    snapshotAgeHours: Annotated[float, Field(ge=0)]
    signalStatus: Literal['held']
    signalHoldReason: str

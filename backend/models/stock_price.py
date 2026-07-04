from pydantic import BaseModel


class StockPriceItem(BaseModel):
    trade_date: str
    open: int | None = None
    high: int | None = None
    low: int | None = None
    close: int | None = None
    volume: int | None = None
    market_cap: int | None = None


class StockPriceResponse(BaseModel):
    items: list[StockPriceItem]


class ValuationItem(BaseModel):
    trade_date: str
    close: int | None = None
    bps: float | None = None
    per: float | None = None
    pbr: float | None = None
    eps: float | None = None
    div_yield: float | None = None


class ValuationResponse(BaseModel):
    items: list[ValuationItem]
    pbr_bands: dict[str, list[float | None]] | None = None

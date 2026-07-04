from pydantic import BaseModel


class WatchlistCreate(BaseModel):
    stock_code: str
    conviction: int | None = None
    target_price: int | None = None
    thesis: str | None = None


class WatchlistUpdate(BaseModel):
    conviction: int | None = None
    target_price: int | None = None
    thesis: str | None = None


class WatchlistResponse(BaseModel):
    id: int
    stock_code: str
    corp_code: str
    corp_name: str
    conviction: int | None = None
    target_price: int | None = None
    thesis: str | None = None
    created_at: str
    updated_at: str
    latest_close: int | None = None
    latest_market_cap: int | None = None
    gap_pct: float | None = None

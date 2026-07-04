from pydantic import BaseModel


class CompanyResponse(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str | None = None
    market: str | None = None
    sector: str | None = None

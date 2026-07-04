from pydantic import BaseModel


class DisclosureItem(BaseModel):
    rcp_no: str
    corp_name: str | None = None
    report_nm: str | None = None
    rcept_dt: str | None = None
    flr_nm: str | None = None
    rm: str | None = None
    dart_url: str | None = None


class DisclosureResponse(BaseModel):
    items: list[DisclosureItem]
    total: int

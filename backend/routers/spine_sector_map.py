"""산업/섹터 맵 API — RS 4사분면 (pipeline/sector_rs)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/sector-map", tags=["spine"])


class TrailPoint(BaseModel):
    weeks_ago: int
    rs_long: float | None
    rs_short: float | None


class SectorGroup(BaseModel):
    name: str
    market_cap: float
    stocks: int
    rs_long: float | None
    rs_short: float | None
    chg_5d: float
    trail: list[TrailPoint]


class SectorMapResponse(BaseModel):
    as_of: str | None
    groups: list[SectorGroup]


@router.get("", response_model=SectorMapResponse)
def sector_map():
    from pipeline.sector_rs import compute_sector_map
    return compute_sector_map()


class MemberRow(BaseModel):
    stock_code: str
    corp_name: str
    market_cap: float | None
    rs_long: float | None
    rs_short: float | None
    ret_1m: float | None
    ret_12m: float | None


class GroupMembersResponse(BaseModel):
    group: str
    as_of: str | None = None
    items: list[MemberRow]


@router.get("/members", response_model=GroupMembersResponse)
def group_members(group: str):
    from pipeline.sector_rs import group_members_rs
    return group_members_rs(group)

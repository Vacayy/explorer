"""산업/섹터 맵 API — RS 4사분면 (pipeline/sector_rs)."""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.sector_peers import SectorPeersResponse

router = APIRouter(prefix="/api/spine/sector-map", tags=["spine"])
logger = logging.getLogger(__name__)


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


class ChainStage(BaseModel):
    stage_name: str
    themes: list[str]


class ValueChainResponse(BaseModel):
    group: str
    stages: list[ChainStage]


@router.get("/chain", response_model=ValueChainResponse)
def value_chain(group: str):
    """대분류 밸류체인 단계·테마 (LLM 시드, value_chains)."""
    import json
    from database import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT stage_name, themes_json FROM value_chains WHERE group_name=? ORDER BY stage_idx",
        (group,)).fetchall()
    conn.close()
    return ValueChainResponse(group=group, stages=[
        ChainStage(stage_name=r["stage_name"], themes=json.loads(r["themes_json"])) for r in rows])


@router.get("/peers", response_model=SectorPeersResponse)
def sector_peers():
    """섹터 → Peer 그룹 대응(sector_peer_map) + 그룹별 섹터 비중 · 연결 없는 섹터의 자동 제안. 모델 호출 없음."""
    from database import get_connection
    from pipeline.sector_peers import sector_peers as build
    from routers.peers import read_runtime
    try:
        runtime = read_runtime()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Invalid Peer runtime snapshot: %s", exc)
        raise HTTPException(status_code=503, detail="Peer 저장 자료를 읽거나 검증하지 못했습니다.") from exc
    conn = get_connection()
    try:
        return build(conn, runtime)
    finally:
        conn.close()

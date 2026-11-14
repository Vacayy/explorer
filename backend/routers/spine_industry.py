"""산업 › 섹터 지도 · 섹터 화면 API (ia-redesign §4.35, D-327 · 미국 §4.36) — 저장분만 읽는다(외부·모델 호출 없음)."""
import logging

from fastapi import APIRouter, HTTPException, Request

from models.industry import (IndustryMapResponse, SectorDetailResponse, SectorPeerListResponse, UsIndustryMapResponse,
                             UsSectorDetailResponse)

router = APIRouter(prefix="/api/spine/industry", tags=["spine"])
logger = logging.getLogger(__name__)


def _runtime(required: bool):
    """Peer 게시본 — 지도·개요는 없어도 나머지를 보인다(null), Peer 탭은 503."""
    from routers.peers import read_runtime
    try:
        return read_runtime()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Invalid Peer runtime snapshot: %s", exc)
        if required:
            raise HTTPException(status_code=503, detail="Peer 저장 자료를 읽거나 검증하지 못했습니다.") from exc
        return None


# 미국 라우트를 먼저 — '/{sector}'·'/{sector}/peers'보다 앞에 둔다(§4.36)
@router.get("/us/map", response_model=UsIndustryMapResponse)
def us_industry_map(request: Request):
    """미국 섹터 지도 — GICS 11 + 세부 업종 13 ETF의 RS(24개 간 백분위)·1개월·3개월·1주·4주 경로·61거래일 선 + SPY 선, 내 커버리지 수."""
    from database import get_connection
    from pipeline.us_sectors import us_map
    from security.public_industry import industry_connection
    public = getattr(request.state, 'public_access', False)
    conn = industry_connection() if public else get_connection()
    try:
        return us_map(conn, include_coverage=not public)
    finally:
        conn.close()


@router.get("/us/{ticker}", response_model=UsSectorDetailResponse)
def us_sector_detail(ticker: str):
    """미국 섹터 화면 — ETF 머리·ETF vs SPY·같은 상위 섹터 안 비교·내 커버리지 종목·주요 자료·이 산업의 데이터."""
    from database import get_connection
    from pipeline.us_sectors import us_sector_detail as build
    conn = get_connection()
    try:
        out = build(conn, ticker)
    finally:
        conn.close()
    if out is None:
        raise HTTPException(status_code=404, detail="없는 미국 섹터 ETF입니다.")
    return out


@router.get("/map", response_model=IndustryMapResponse)
def industry_map():
    """섹터 지도 — 섹터마다 대표지수(ETF 또는 계산 지수)·1일·1개월·3개월·RS·61거래일 선 + 코스피 선, 섹터 밖 Peer 그룹."""
    from database import get_connection
    from pipeline.sector_view import industry_map as build
    conn = get_connection()
    try:
        return build(conn, _runtime(False))
    finally:
        conn.close()


@router.get("/{sector}", response_model=SectorDetailResponse)
def sector_detail(sector: str):
    """섹터 화면 머리·개요·종목 — 대표지수 vs 코스피, RS 흐름, 비중 상위, 내러티브·AI 개괄, 주요 자료, Peer 미리보기, 데이터 연결."""
    from database import get_connection
    from pipeline.sector_view import sector_detail as build
    conn = get_connection()
    try:
        out = build(conn, sector, _runtime(False))
    finally:
        conn.close()
    if out is None:
        raise HTTPException(status_code=404, detail="없는 섹터입니다.")
    return out


@router.get("/{sector}/peers", response_model=SectorPeerListResponse)
def sector_peers(sector: str):
    """섹터의 하위 Peer 그룹 — 대응표 그룹과 그 아래 제품 그룹, 종목 수·20·60거래일 중앙값."""
    from database import get_connection
    from pipeline.sector_view import sector_peer_list
    runtime = _runtime(True)
    conn = get_connection()
    try:
        out = sector_peer_list(conn, sector, runtime)
    finally:
        conn.close()
    if out is None:
        raise HTTPException(status_code=404, detail="없는 섹터입니다.")
    return out

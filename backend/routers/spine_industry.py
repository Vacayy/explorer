"""산업 › 섹터 지도 · 섹터 화면 API (ia-redesign §4.35, D-327) — 저장분만 읽는다(외부·모델 호출 없음)."""
import logging

from fastapi import APIRouter, HTTPException

from models.industry import IndustryMapResponse, SectorDetailResponse, SectorPeerListResponse

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

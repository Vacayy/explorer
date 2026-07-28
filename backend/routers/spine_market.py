"""시장 국면 API (market regime, D-076, docs/specs/market-regime.md).

GET  /api/spine/market-regime          — 양 시장 포스처 + 스파크라인 (LLM 0, 읽기)
POST /api/spine/market-regime/snapshot — 일별 스냅샷 적재 (EOD 배치·수동 트리거)

첫 조회 시 스냅샷이 비어 있으면 lazy 1회 수집(외부 fetch ~수 초).
"""
from fastapi import APIRouter

from pipeline.market_regime import get_regime, snapshot_market

router = APIRouter(prefix="/api/spine/market-regime", tags=["spine"])


@router.get("")
def market_regime():
    data = get_regime()
    if data["as_of"] is None:      # 첫 진입 — lazy 스냅샷
        snapshot_market()
        data = get_regime()
    return data


@router.post("/snapshot")
def snapshot():
    return snapshot_market()

"""매크로·유동성 API (docs/specs/macro.md).

GET  /api/spine/macro          — 지표 그룹 + 스파크라인 (LLM 0, 순수 읽기). 첫 진입 시 lazy 스냅샷.
POST /api/spine/macro/snapshot — 지표 재수집 적재 (수동 버튼·선택 크론).
"""
from fastapi import APIRouter

from pipeline.macro import get_macro, snapshot_macro

router = APIRouter(prefix="/api/spine/macro", tags=["spine"])


@router.get("")
def macro():
    data = get_macro()
    if data["as_of"] is None:      # 첫 진입 — lazy 스냅샷 1회
        snapshot_macro()
        data = get_macro()
    return data


@router.post("/snapshot")
def snapshot():
    return snapshot_macro()

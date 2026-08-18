"""국내시장 API (D-108) — 전일 거래대금 상위 + 섹터 쏠림.

미국장(`/api/spine/us/movers`·`/briefing`)의 국장 대응물이되 LLM 종합은 없다.
로드는 순수 읽기(네트워크·LLM 0), 갱신은 `?force=true` 버튼만 — D-100 버튼 주도 규약.
"""
from fastapi import APIRouter

from models.kr import KrMovers

router = APIRouter(prefix="/api/spine/kr", tags=["spine"])


@router.get("/movers", response_model=KrMovers)
def kr_movers(force: bool = False):
    """전일 국내 거래대금 상위 20 + 섹터 쏠림 + 개별 이슈. 전부 LLM 0.

    force=false: 마지막 스냅샷 읽기 · force=true: FDR 재수집 후 반환.
    """
    from pipeline.kr_movers import get_leaders, read_leaders
    return KrMovers(**(get_leaders(force=True) if force else read_leaders()))

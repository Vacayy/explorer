"""Market Today API (docs/specs/market-today.md) — 장중 회차 화두 요약 읽기. 생성은 정기 작업(scripts/market_today.py).

화두 → 내러티브 연결(ia-redesign §9): 회차 items의 `narratives`, 내러티브 상세 타임라인, 내러티브 후보(승인·무시).
전부 결정적 — LLM을 부르지 않는다. 승인은 다음 내러티브 갱신 때 첫 버전을 만들도록 등록만 한다.
"""
from fastapi import APIRouter, HTTPException, Path, Query

from database import get_connection
from models.market_today import CandidateAction, MarketToday, NarrativeCandidates, NarrativeMarketToday

router = APIRouter(tags=["spine"])


@router.get("/api/spine/market-today", response_model=MarketToday)
def market_today(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                 slot: str | None = Query(None, pattern=r"^(0930|1130|1500|1600|1000|1300|1540)$")):
    """그날(없으면 최근) 회차 목록과 선택(없으면 최신) 회차의 화두·출처·연결 내러티브. LLM 0."""
    from pipeline.market_today import read
    return read(date, slot)


@router.get("/api/spine/narratives/{narrative_id}/market-today", response_model=NarrativeMarketToday)
def narrative_market_today(narrative_id: int):
    """내러티브 상세 '장중 화두 타임라인' — 최근 2일 회차 격자·연결 화두·이번 주 집계."""
    from pipeline.market_today_links import timeline
    conn = get_connection()
    try:
        out = timeline(conn, narrative_id)
    finally:
        conn.close()
    if out is None:
        raise HTTPException(404, "내러티브를 찾을 수 없습니다")
    return out


@router.get("/api/spine/narrative-candidates", response_model=NarrativeCandidates)
def narrative_candidates():
    """Market Today에서 반복되는데 전용 서사가 없는 화두 묶음 — 후보·승인 대기·관찰 중."""
    from pipeline.market_today_links import list_candidates
    conn = get_connection()
    try:
        return {"items": list_candidates(conn)}
    finally:
        conn.close()


def _act(fn, tag: str) -> dict:
    conn = get_connection()
    try:
        out = fn(conn, tag)
    finally:
        conn.close()
    if out is None:
        raise HTTPException(409, "지금 처리할 수 있는 후보가 아닙니다")
    return out


@router.post("/api/spine/narrative-candidates/{tag}/approve", response_model=CandidateAction)
def approve_candidate(tag: str = Path(..., max_length=80)):
    """[서사로 만들기]·[○○에 합치기] — 생성하지 않고 다음 내러티브 갱신에 등록(합치기는 즉시 다시 연결)."""
    from pipeline.market_today_links import approve
    return _act(approve, tag)


@router.post("/api/spine/narrative-candidates/{tag}/dismiss", response_model=CandidateAction)
def dismiss_candidate(tag: str = Path(..., max_length=80)):
    """[무시] — 14일 동안 다시 후보로 올리지 않는다."""
    from pipeline.market_today_links import dismiss
    return _act(dismiss, tag)

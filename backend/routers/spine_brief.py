"""종목 AI 브리프 API — P2-1. 소스 도시에와 동일한 2단 패턴:
GET = LLM 없이 즉시 (캐시 + stale 플래그) / POST = 입력 변경 시만 생성."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/stock", tags=["spine"])


class StockBrief(BaseModel):
    status: str                # fresh | cached | empty | unavailable | failed
    brief: str | None
    thesis_check: str | None   # 내 논지 vs 새 증거 (충돌/지지)
    created_at: str | None
    stale: bool = False


@router.get("/{stock_code}/brief", response_model=StockBrief)
def get_brief(stock_code: str):
    """캐시된 브리프 + stale 플래그 — LLM 호출 없음."""
    from pipeline.stock_brief import (_resolve_entity, gather_inputs, get_cached,
                                      inputs_hash, _has_material)
    conn = get_connection()
    ent = _resolve_entity(conn, stock_code)
    if not ent:
        conn.close()
        raise HTTPException(404, "종목 엔티티가 없습니다")
    inp = gather_inputs(conn, stock_code, ent["id"])
    if not _has_material(inp):
        conn.close()
        return StockBrief(status="empty", brief=None, thesis_check=None, created_at=None)
    cached = get_cached(conn, ent["id"])
    stale = not cached or cached["inputs_hash"] != inputs_hash(inp)
    conn.close()
    if not cached:
        return StockBrief(status="empty", brief=None, thesis_check=None,
                          created_at=None, stale=True)
    return StockBrief(status="cached", brief=cached["brief"],
                      thesis_check=cached["thesis_check"],
                      created_at=cached["created_at"], stale=stale)


@router.post("/{stock_code}/brief/compute", response_model=StockBrief)
def compute_brief_endpoint(stock_code: str):
    """입력(다이제스트·신호·일정·논지)이 바뀌었을 때만 LLM 생성 — 멱등."""
    from pipeline.stock_brief import compute_brief
    r = compute_brief(stock_code)
    if r.get("status") == "not_found":
        raise HTTPException(404, "종목 엔티티가 없습니다")
    return StockBrief(status=r["status"], brief=r.get("brief"),
                      thesis_check=r.get("thesis_check"), created_at=r.get("created_at"))

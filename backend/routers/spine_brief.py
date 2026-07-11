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
    evidence: list[str] = []   # 근거 재료 인벤토리 (다이제스트·신호·공시·일정·논지)


_SIGNAL_LABEL = {"mention_surge": "언급 급증", "high_52w": "52주 신고가"}


def _evidence(inp: dict) -> list[str]:
    """브리프에 들어간 재료를 사람이 읽을 칩으로 — '이 브리프는 무엇을 보고 썼나'."""
    ev = []
    for period, d in sorted(inp["digests"].items()):
        ev.append(f"언급 요약 {period.upper()} ({d['period_start']})")
    for s in inp["signals"]:
        ev.append(f"신호 · {_SIGNAL_LABEL.get(s['signal_type'], s['signal_type'])} ({s['date']})")
    for a in inp["actions"]:
        dt = a["rcept_dt"]
        ev.append(f"공시 · {a['action_type']} ({dt[4:6]}-{dt[6:8]})")
    for c in inp["upcoming"]:
        ev.append(f"일정 · {c['event_type']} ({c['event_date']})")
    t = inp["thesis"]
    if (t and t["thesis"]) or inp["notes"]:
        ev.append(f"내 논지 ({len(inp['notes'])}건)")
    return ev


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
    ev = _evidence(inp)
    if not cached:
        return StockBrief(status="empty", brief=None, thesis_check=None,
                          created_at=None, stale=True, evidence=ev)
    return StockBrief(status="cached", brief=cached["brief"],
                      thesis_check=cached["thesis_check"],
                      created_at=cached["created_at"], stale=stale, evidence=ev)


class BriefHistoryItem(BaseModel):
    brief: str | None
    thesis_check: str | None
    created_at: str


@router.get("/{stock_code}/brief/history", response_model=list[BriefHistoryItem])
def brief_history(stock_code: str, limit: int = 10):
    """지난 브리프 아카이브 — 최신 제외, 시점 역순."""
    from pipeline.stock_brief import _resolve_entity
    conn = get_connection()
    ent = _resolve_entity(conn, stock_code)
    if not ent:
        conn.close()
        raise HTTPException(404, "종목 엔티티가 없습니다")
    rows = conn.execute("""
        SELECT brief, thesis_check, created_at FROM stock_briefs
        WHERE entity_id=? ORDER BY id DESC LIMIT ?""", (ent["id"], limit + 1)).fetchall()
    conn.close()
    return [BriefHistoryItem(brief=r["brief"], thesis_check=r["thesis_check"],
                             created_at=r["created_at"]) for r in rows[1:]]


@router.post("/{stock_code}/brief/compute", response_model=StockBrief)
def compute_brief_endpoint(stock_code: str):
    """입력(다이제스트·신호·일정·논지)이 바뀌었을 때만 LLM 생성 — 멱등."""
    from pipeline.stock_brief import compute_brief
    r = compute_brief(stock_code)
    if r.get("status") == "not_found":
        raise HTTPException(404, "종목 엔티티가 없습니다")
    return StockBrief(status=r["status"], brief=r.get("brief"),
                      thesis_check=r.get("thesis_check"), created_at=r.get("created_at"))

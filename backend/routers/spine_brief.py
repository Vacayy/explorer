"""종목 AI 브리프 API — P2-1. 소스 도시에와 동일한 2단 패턴:
GET = LLM 없이 즉시 (캐시 + stale 플래그) / POST = 입력 변경 시만 생성."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/stock", tags=["spine"])


class RevisionCall(BaseModel):
    direction: str             # up | down | hold
    rationale: str | None = None


class StockBrief(BaseModel):
    status: str                # fresh | cached | empty | unavailable | failed
    brief: str | None
    thesis_check: str | None   # 내 논지 vs 새 증거 (충돌/지지)
    revision_call: RevisionCall | None = None  # 추정치 방향 콜 (기록되어 실측 대조)
    created_at: str | None
    stale: bool = False
    evidence: list[str] = []   # 근거 재료 인벤토리 (다이제스트·신호·공시·일정·논지)
    has_thesis: bool = True    # false면 FE가 논지 등록 입력을 띄운다
    thesis: str | None = None  # 논지 원문 (불변 저장 — AI는 점검만 하고 원문은 안 고친다)


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
    if inp.get("knowledge"):
        ev.append(f"승격 지식 {len(inp['knowledge'])}건")
    if inp.get("decomp"):
        ev.append(f"상승 분해 ({inp['decomp']['year']}년 실적 기준)")
    if inp.get("consensus"):
        ev.append("컨센서스 (Fwd EPS·목표가)")
    if inp.get("flows"):
        ev.append(f"수급 {inp['flows']['days']}거래일")
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
    t = inp["thesis"]
    has_thesis = bool((t and t["thesis"]) or inp["notes"])
    thesis_text = t["thesis"] if (t and t["thesis"]) else None
    if not cached:
        return StockBrief(status="empty", brief=None, thesis_check=None,
                          created_at=None, stale=True, evidence=ev,
                          has_thesis=has_thesis, thesis=thesis_text)
    from pipeline.stock_brief import _parse_call
    return StockBrief(status="cached", brief=cached["brief"],
                      thesis_check=cached["thesis_check"],
                      revision_call=_parse_call(cached["revision_call"]),
                      created_at=cached["created_at"], stale=stale, evidence=ev,
                      has_thesis=has_thesis, thesis=thesis_text)


class PeerRow(BaseModel):
    name: str
    ticker: str
    market: str
    is_self: bool = False
    market_cap: float | None = None
    currency: str | None = None
    per_fwd: float | None = None
    op_margin: float | None = None


@router.get("/{stock_code}/peers", response_model=list[PeerRow])
def stock_peers(stock_code: str):
    """Peer 그룹 비교 — 본 종목 + peer들의 시총·PER(fwd)·영업이익률.

    peer 목록은 haiku 큐레이션 1회 캐시, 지표는 KR=자체 데이터 / 해외=yfinance(24h 캐시).
    첫 호출은 LLM+외부 조회로 수 초~수십 초 걸릴 수 있다 (이후 캐시 즉답).
    """
    from pipeline.peers import get_peer_list, get_peer_metrics, _kr_metrics
    conn = get_connection()
    row = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?", (stock_code,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "종목을 찾을 수 없습니다")

    out = []
    self_m = _kr_metrics(stock_code) or {}
    out.append(PeerRow(name=row["corp_name"], ticker=f"{stock_code}.KS", market="KR",
                       is_self=True, **{k: self_m.get(k) for k in ("market_cap", "currency", "per_fwd", "op_margin")}))
    for p in get_peer_list(stock_code, row["corp_name"]):
        if p["ticker"].split(".")[0] == stock_code:
            continue
        m = get_peer_metrics(p["ticker"], p["market"]) or {}
        out.append(PeerRow(name=p["name"], ticker=p["ticker"], market=p["market"],
                           **{k: m.get(k) for k in ("market_cap", "currency", "per_fwd", "op_margin")}))
    return out


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
                      thesis_check=r.get("thesis_check"),
                      revision_call=r.get("revision_call"), created_at=r.get("created_at"))

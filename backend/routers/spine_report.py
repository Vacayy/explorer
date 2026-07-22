"""통합 리포트 API — 공유 인과 내러티브 취합 → 종목 재분석 → Top-down 리포트 (integrated-report)."""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/report", tags=["spine"])


class ReportResult(BaseModel):
    status: str                      # ok | none | unavailable | error
    id: int | None = None            # 이 버전의 report id (히스토리, D-047)
    title: str | None = None
    answer: str | None = None        # Top-down 마크다운
    members: list[str] = []          # 취합된 내러티브 topic
    stocks: list[dict] = []          # 분석 종목 [{code,name,rating,upside_pct}]
    top_pick: str | None = None      # Top-pick 종목코드 (A)
    debate: dict = {}                # analyst·bull·bear·ratings (v2 산출물 열람, D-043)
    cached: bool = False
    created_at: str | None = None


class ReportListItem(BaseModel):
    anchor_topic: str
    title: str | None
    n_members: int
    n_stocks: int
    created_at: str


class ReportVersion(BaseModel):
    id: int
    title: str | None
    top_pick: str | None
    created_at: str


def _row_to_result(row) -> ReportResult:
    return ReportResult(
        status="ok", id=row["id"], title=row["title"], answer=row["body"],
        members=json.loads(row["members_json"] or "[]"),
        stocks=json.loads(row["stocks_json"] or "[]"),
        top_pick=row["top_pick"], debate=json.loads(row["debate_json"] or "{}"),
        cached=True, created_at=row["created_at"])


@router.get("/list", response_model=list[ReportListItem])
def report_list():
    """발간된 통합 리포트 목록 — topic별 최신 버전, 최신순. LLM 없음."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT r.anchor_topic, r.title, r.members_json, r.stocks_json, r.created_at "
        "FROM reports r JOIN (SELECT anchor_topic, MAX(id) mid FROM reports GROUP BY anchor_topic) t "
        "ON t.mid=r.id ORDER BY r.created_at DESC").fetchall()
    conn.close()
    return [ReportListItem(
        anchor_topic=r["anchor_topic"], title=r["title"],
        n_members=len(json.loads(r["members_json"] or "[]")),
        n_stocks=len(json.loads(r["stocks_json"] or "[]")),
        created_at=r["created_at"]) for r in rows]


@router.get("/history", response_model=list[ReportVersion])
def report_history(topic: str):
    """한 주제의 과거 리포트 버전 목록 — 최신순 (append-only, D-047). LLM 없음."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, top_pick, created_at FROM reports WHERE anchor_topic=? ORDER BY id DESC",
        (topic,)).fetchall()
    conn.close()
    return [ReportVersion(id=r["id"], title=r["title"], top_pick=r["top_pick"],
                          created_at=r["created_at"]) for r in rows]


@router.get("/version", response_model=ReportResult)
def report_version(id: int):
    """특정 버전 리포트 열람 (히스토리, D-047) — LLM 없음."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, title, body, members_json, stocks_json, debate_json, top_pick, created_at "
        "FROM reports WHERE id=?", (id,)).fetchone()
    conn.close()
    return _row_to_result(row) if row else ReportResult(status="none")


@router.get("", response_model=ReportResult)
def report_cached(topic: str):
    """저장된 통합 리포트 — 최신 버전. LLM 없음. 없으면 status=none."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, title, body, members_json, stocks_json, debate_json, top_pick, created_at "
        "FROM reports WHERE anchor_topic=? ORDER BY id DESC LIMIT 1", (topic,)).fetchone()
    conn.close()
    return _row_to_result(row) if row else ReportResult(status="none")


@router.post("/compute", response_model=ReportResult)
def report_compute(topic: str, refresh: bool = False):
    """통합 리포트 생성 — 연쇄 LLM(종목별 sonnet ×M + 리포트 opus). 구성원 내러티브 변동 없으면
    저장분 반환, refresh=1일 때만 재생성. 무겁다(수 분)."""
    from pipeline.report import build_report
    conn = get_connection()
    try:
        r = build_report(conn, topic, force=refresh)
    except Exception:
        conn.close()
        return ReportResult(status="error")
    conn.close()
    if r.get("error"):
        return ReportResult(status="unavailable")
    return ReportResult(status="ok", title=r.get("title"), answer=r.get("answer"),
                        members=r.get("members") or [], stocks=r.get("stocks") or [],
                        top_pick=r.get("top_pick"), debate=r.get("debate") or {},
                        cached=bool(r.get("cached")), created_at=r.get("created_at"))

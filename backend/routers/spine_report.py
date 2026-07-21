"""통합 리포트 API — 공유 인과 내러티브 취합 → 종목 재분석 → Top-down 리포트 (integrated-report)."""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/report", tags=["spine"])


class ReportResult(BaseModel):
    status: str                      # ok | none | unavailable | error
    title: str | None = None
    answer: str | None = None        # Top-down 마크다운
    members: list[str] = []          # 취합된 내러티브 topic
    stocks: list[dict] = []          # 분석 종목 [{code,name}]
    cached: bool = False
    created_at: str | None = None


@router.get("", response_model=ReportResult)
def report_cached(topic: str):
    """저장된 통합 리포트 조회 — LLM 없음. 없으면 status=none."""
    conn = get_connection()
    row = conn.execute(
        "SELECT title, body, members_json, stocks_json, created_at FROM reports WHERE anchor_topic=?",
        (topic,)).fetchone()
    conn.close()
    if not row:
        return ReportResult(status="none")
    return ReportResult(
        status="ok", title=row["title"], answer=row["body"],
        members=json.loads(row["members_json"] or "[]"),
        stocks=json.loads(row["stocks_json"] or "[]"),
        cached=True, created_at=row["created_at"])


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
                        cached=bool(r.get("cached")), created_at=r.get("created_at"))

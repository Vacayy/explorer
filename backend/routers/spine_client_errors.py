"""화면 API 오류 기록 (docs/specs/frontend-api-reliability.md §오류 기록).

프런트 응답 래퍼가 응답 계약 위반·5xx·timeout·네트워크 오류를 보고하면 같은 API·같은 필드·같은 종류끼리
한 행으로 묶어 횟수와 처음·마지막 발생 시각을 쌓는다. 화면에는 일반 문구만 보이고 원인이 사라지던 문제
(2026-10-31: 주가 응답의 market_cap 누락이 모든 기업 상세 차트를 막았지만 어디에도 남지 않았다) 대응.
'운영' 점검(pipeline/health.py)이 최근 24시간 기록을 비정상으로 올린다.
"""
import hashlib
import json

from fastapi import APIRouter

from database import get_connection
from models.client_errors import ClientError, ClientErrorReport

router = APIRouter(prefix="/api/spine/client-errors", tags=["spine"])


@router.post("", status_code=204)
def report(body: ClientErrorReport):
    sig = hashlib.sha1(f"{body.endpoint}|{body.kind}|{body.status}|{body.field}".encode()).hexdigest()[:16]
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO client_errors (signature, endpoint, kind, status, field, detail, issues_json, page, count, first_seen, last_seen) "
            "VALUES (?,?,?,?,?,?,?,?,1, datetime('now'), datetime('now')) ON CONFLICT(signature) DO UPDATE SET "
            "count=client_errors.count+1, last_seen=datetime('now'), detail=excluded.detail, issues_json=excluded.issues_json, page=excluded.page",
            (sig, body.endpoint, body.kind, body.status, body.field, body.detail,
             json.dumps(body.issues, ensure_ascii=False, default=str)[:4000], body.page))
        conn.commit()
    finally:
        conn.close()


@router.get("", response_model=list[ClientError])
def recent(days: int = 7, limit: int = 100):
    """최근 기록 — 마지막 발생순."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT signature, endpoint, kind, status, field, detail, page, count, first_seen, last_seen FROM client_errors "
                            "WHERE last_seen >= datetime('now', ?) ORDER BY last_seen DESC LIMIT ?", (f"-{max(1, days)} days", min(limit, 500))).fetchall()
        return [ClientError(**dict(r)) for r in rows]
    finally:
        conn.close()

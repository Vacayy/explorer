"""기업활동 API — 시총 5,000억+ 유·무상증자/합병/분할/공개매수/감자."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/actions", tags=["spine"])


class CorporateAction(BaseModel):
    id: int
    rcp_no: str
    corp_name: str | None
    stock_code: str | None
    market: str | None        # Y=유가 K=코스닥
    action_type: str
    report_nm: str | None
    rcept_dt: str             # YYYYMMDD
    market_cap: int | None
    summary: str | None       # haiku 핵심 요약 (규모·비율·일정)
    dart_url: str


class ActionsResponse(BaseModel):
    items: list[CorporateAction]
    total: int
    as_of: str


@router.get("", response_model=ActionsResponse)
def list_actions(
    type: str | None = Query(None, description="유상증자|무상증자|공개매수|주식분할|합병|회사분할|감자"),
    days: int = Query(30, ge=1, le=180),
):
    conn = get_connection()
    where, params = ["rcept_dt >= ?"], [(date.today() - timedelta(days=days)).strftime("%Y%m%d")]
    if type:
        where.append("action_type = ?")
        params.append(type)
    rows = conn.execute(f"""
        SELECT * FROM corporate_actions WHERE {" AND ".join(where)}
        ORDER BY rcept_dt DESC, id DESC LIMIT 200
    """, params).fetchall()
    conn.close()
    return ActionsResponse(
        items=[CorporateAction(
            id=r["id"], rcp_no=r["rcp_no"], corp_name=r["corp_name"],
            stock_code=r["stock_code"], market=r["market"], action_type=r["action_type"],
            report_nm=r["report_nm"], rcept_dt=r["rcept_dt"], market_cap=r["market_cap"],
            summary=r["summary"],
            dart_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcp_no']}",
        ) for r in rows],
        total=len(rows),
        as_of=datetime.now(timezone.utc).isoformat(),
    )

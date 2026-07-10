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


class RightsRow(BaseModel):
    rcp_no: str
    stock_code: str | None
    corp_name: str | None
    action_type: str | None
    method: str | None
    price_1st: int | None
    price_2nd: int | None
    price_final: int | None
    latest_close: int | None
    diff_w: int | None          # 현재가 - 유효발행가 (확정>2차>1차 순)
    diff_pct: float | None
    old_shares: int | None
    new_shares: int | None
    ratio_pct: float | None     # 증자비율
    date_disclosure: str | None
    date_price_1st: str | None
    date_ex_rights: str | None
    date_record: str | None
    date_rights_listing_start: str | None
    date_price_fix: str | None
    date_sub_start: str | None
    date_public_start: str | None
    date_payment: str | None
    date_rights_listing_end: str | None   # 권리매도 마감
    date_new_listing: str | None
    underwriter: str | None
    major_holder: str | None
    dart_url: str


class RightsResponse(BaseModel):
    items: list[RightsRow]
    as_of: str


@router.get("/rights", response_model=RightsResponse)
def list_rights():
    """유·무상증자 Pro 뷰 — 결정 공시별 구조화 상세 + 현재가 대비 차액."""
    conn = get_connection()
    # 종목·타입별 최신 결정 공시만 (기재정정이 이전 것을 대체)
    rows = conn.execute("""
        SELECT d.* FROM capital_raise_details d
        JOIN (SELECT stock_code, action_type, max(rcp_no) mx FROM capital_raise_details
              GROUP BY stock_code, action_type) t
          ON d.stock_code = t.stock_code AND d.action_type = t.action_type AND d.rcp_no = t.mx
        ORDER BY d.date_disclosure DESC
    """).fetchall()
    closes = {r["stock_code"]: r["close"] for r in conn.execute("""
        SELECT stock_code, close FROM stock_prices
        WHERE (stock_code, trade_date) IN (
            SELECT stock_code, max(trade_date) FROM stock_prices GROUP BY stock_code)
    """)}
    conn.close()

    items = []
    for r in rows:
        eff = r["price_final"] or r["price_2nd"] or r["price_1st"]
        close = closes.get(r["stock_code"])
        diff_w = (close - eff) if (close and eff) else None
        diff_pct = round(diff_w / eff * 100, 2) if (diff_w is not None and eff) else None
        ratio = round(r["new_shares"] / r["old_shares"] * 100, 2) \
            if (r["new_shares"] and r["old_shares"]) else None
        items.append(RightsRow(
            **{k: r[k] for k in (
                "rcp_no", "stock_code", "corp_name", "action_type", "method",
                "price_1st", "price_2nd", "price_final", "old_shares", "new_shares",
                "date_disclosure", "date_price_1st", "date_ex_rights", "date_record",
                "date_rights_listing_start", "date_price_fix", "date_sub_start",
                "date_public_start", "date_payment", "date_rights_listing_end",
                "date_new_listing", "underwriter", "major_holder")},
            latest_close=close, diff_w=diff_w, diff_pct=diff_pct, ratio_pct=ratio,
            dart_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcp_no']}",
        ))
    return RightsResponse(items=items, as_of=datetime.now(timezone.utc).isoformat())

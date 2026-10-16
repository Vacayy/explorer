"""기업활동 API — 시총 5,000억+ 유·무상증자/합병/분할/공개매수/감자."""
from datetime import date, timedelta
from typing import Literal

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
    is_correction: bool = False   # report_nm에 '정정'([기재정정]·[첨부정정]) — 원공시를 고친 것
    my_group: str | None = None   # 내 묶음(stock_groups) 멤버면 '보유'(portfolio) 또는 '관심'(watch)


class ActionCounts(BaseModel):
    original: int
    correction: int


class ActionsResponse(BaseModel):
    items: list[CorporateAction]
    total: int
    as_of: str | None         # 마지막 DART 스캔 성공 시각(UTC). 스캔 기록이 없으면 None
    counts: ActionCounts | None = None   # kind 필터 전, 같은 기간·유형 안의 원공시·정정 수


def _scanned_at(conn) -> str | None:
    """마지막 scan_actions 성공 시각 — 서버 now를 쓰면 스캔이 실패해도 늘 '방금'으로 보였다."""
    r = conn.execute("SELECT max(ran_at) FROM job_runs WHERE job='scan_actions' AND status='ok'").fetchone()[0]
    return f"{r.replace(' ', 'T')}Z" if r else None


_IS_CORRECTION = "COALESCE(report_nm, '') LIKE '%정정%'"


def my_groups(conn) -> dict[str, str]:
    """종목코드 → '보유'|'관심' — 보유(portfolio 묶음)가 관심보다 우선."""
    out: dict[str, str] = {}
    for r in conn.execute("SELECT m.stock_code, g.kind FROM stock_group_members m "
                          "JOIN stock_groups g ON g.id = m.group_id ORDER BY g.kind = 'portfolio'"):
        out[r["stock_code"]] = "보유" if r["kind"] == "portfolio" else "관심"
    return out


@router.get("", response_model=ActionsResponse)
def list_actions(
    type: str | None = Query(None, description="유상증자|무상증자|공개매수|주식분할|합병|회사분할|감자"),
    days: int = Query(30, ge=1, le=180),
    kind: Literal["all", "original", "correction"] = Query("all", description="원공시만 | 정정만 | 전체"),
    stock_code: str | None = Query(None, description="한 종목만 (종목 도시에)"),
):
    conn = get_connection()
    where, params = ["rcept_dt >= ?"], [(date.today() - timedelta(days=days)).strftime("%Y%m%d")]
    if type:
        where.append("action_type = ?")
        params.append(type)
    if stock_code:
        where.append("stock_code = ?")
        params.append(stock_code)
    c = conn.execute(f"SELECT count(*) n, COALESCE(sum({_IS_CORRECTION}), 0) corr FROM corporate_actions "
                     f"WHERE {' AND '.join(where)}", params).fetchone()
    if kind != "all":
        where.append(_IS_CORRECTION if kind == "correction" else f"NOT ({_IS_CORRECTION})")
    rows = conn.execute(f"""
        SELECT * FROM corporate_actions WHERE {" AND ".join(where)}
        ORDER BY rcept_dt DESC, id DESC LIMIT 200
    """, params).fetchall()
    mine = my_groups(conn)
    as_of = _scanned_at(conn)
    conn.close()
    return ActionsResponse(
        items=[CorporateAction(
            id=r["id"], rcp_no=r["rcp_no"], corp_name=r["corp_name"],
            stock_code=r["stock_code"], market=r["market"], action_type=r["action_type"],
            report_nm=r["report_nm"], rcept_dt=r["rcept_dt"], market_cap=r["market_cap"],
            summary=r["summary"],
            dart_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcp_no']}",
            is_correction="정정" in (r["report_nm"] or ""), my_group=mine.get(r["stock_code"]),
        ) for r in rows],
        total=len(rows),
        as_of=as_of,
        counts=ActionCounts(original=c["n"] - c["corr"], correction=c["corr"]),
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
    my_group: str | None = None


class RightsResponse(BaseModel):
    items: list[RightsRow]
    as_of: str | None


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
    as_of = _scanned_at(conn)
    mine = my_groups(conn)
    conn.close()

    items = []
    for r in rows:
        eff = r["price_final"] or r["price_2nd"] or r["price_1st"]
        close = closes.get(r["stock_code"])
        diff_w = (close - eff) if (close and eff) else None
        diff_pct = round(diff_w / eff * 100, 2) if (diff_w is not None and eff) else None
        if diff_pct is not None and abs(diff_pct) > 70:
            # 유증 할인율 범위를 벗어남 — 발행가 추출 오류 의심 → 차액 숨김 (원문 확인 유도)
            diff_w = diff_pct = None
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
            my_group=mine.get(r["stock_code"]),
        ))
    return RightsResponse(items=items, as_of=as_of)

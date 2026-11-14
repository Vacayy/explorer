"""수출입(무역) 팔로우 API (docs/specs/trade-follow.md).

전용 페이지: 좌 팔로우 품목 → 우 수출입 추이 차트 + 관련 종목(LLM 논리 지목, 캐시).
"""
import json

from fastapi import APIRouter, HTTPException, Query
from typing import Literal

from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/trade", tags=["spine"])


class Stat(BaseModel):
    period: str
    export_usd: float | None
    import_usd: float | None
    balance_usd: float | None


class FollowRow(BaseModel):
    hs_code: str
    item_name: str
    group_label: str | None
    latest_period: str | None
    latest_export: float | None
    yoy_pct: float | None
    # D-140 파생지표·판정 (요청 시 계산, trade_metrics) — 기준월=적재 최신월
    mom: float | None = None
    qoq: float | None = None
    yoy3m: float | None = None
    z: float | None = None
    flag: str | None = None          # surge | plunge | new | none
    reason: str | None = None
    contribution: float | None = None
    nested_in: str | None = None     # 이 품목을 포함하는 상위 팔로우 HS(합계·기여도 분모에서 제외)


class StockItem(BaseModel):
    """종목 → 품목 역링크 — 이 종목을 관련 종목으로 지목한 품목과 그 품목의 이번 달 판정."""
    hs_code: str
    item_name: str
    rel: str | None
    period: str | None
    yoy_pct: float | None
    flag: str | None
    reason: str | None


class HighlightRow(BaseModel):
    """급등·급감 품목 — yoy·mom은 비율(0.25 = +25%), contribution은 0~1(전체 증가분 중 몫)."""
    hs_code: str
    item_name: str
    group_label: str | None
    value: float | None
    yoy: float | None = None
    mom: float | None = None
    yoy3m: float | None = None       # 3개월 합의 전년 동기 대비(비율) — 산업 › 수출입 표
    z: float | None = None
    flag: Literal["surge", "plunge", "new"]
    reason: str | None
    contribution: float | None = None
    nested_in: str | None = None


class HighlightGroup(BaseModel):
    group_label: str
    count: int
    value: float
    surge: int
    plunge: int


class Highlights(BaseModel):
    period: str | None
    periods: list[str] = []
    total_usd: float
    surge: list[HighlightRow]
    plunge: list[HighlightRow]
    groups: list[HighlightGroup]   # 수출 규모 순, 판정 수는 전 품목 기준


class Beneficiary(BaseModel):
    name: str
    stock_code: str | None
    rel: str | None
    reason: str | None
    rs: float | None
    per: float | None
    mktcap: float | None
    pos_52w: float | None
    in_universe: bool
    universe_groups: list[str]


class Detail(BaseModel):
    hs_code: str
    item_name: str
    series: list[Stat]
    beneficiaries: list[Beneficiary]


class GridPoint(BaseModel):
    period: str                  # YYYY-MM (빈 달도 격자에 둔다 — 값 null)
    export_usd: float | None
    ma12: float | None           # 12개월 평균(앞 달이 비면 null)


class GridItem(BaseModel):
    """품목 벽 한 칸 — 시계열 + 최신값 + 판정(기준월 = 전체 최신월, highlights와 같은 판정)."""
    hs_code: str
    item_name: str
    group_label: str | None
    latest_period: str | None
    latest_export: float | None
    yoy_pct: float | None        # 최신월 전년 동월 대비(%)
    mom: float | None            # 아래 넷은 비율·0~1 (highlights와 같은 단위)
    yoy3m: float | None
    contribution: float | None
    z: float | None
    flag: Literal["surge", "plunge", "new", "none"]
    stock_codes: list[str]       # 관련 종목(trade_beneficiaries) — '내 종목 관련' 정렬용
    series: list[GridPoint]


class TradeGrid(BaseModel):
    period: str | None
    months: int
    items: list[GridItem]        # 팔로우 품목 중 세목(nested_in) 제외


class FollowReq(BaseModel):
    hs_code: str
    item_name: str | None = None
    group_label: str | None = None
    active: bool = True


def _yoy(conn, hs: str) -> tuple[str | None, float | None, float | None]:
    rows = conn.execute(
        "SELECT period, export_usd FROM trade_stats WHERE hs_code=? ORDER BY period DESC LIMIT 13", (hs,)).fetchall()
    if not rows:
        return None, None, None
    latest = rows[0]
    yoy = None
    if len(rows) >= 13 and rows[12]["export_usd"]:
        yoy = round((latest["export_usd"] / rows[12]["export_usd"] - 1) * 100, 1)
    return latest["period"], latest["export_usd"], yoy


@router.get("/follow", response_model=list[FollowRow])
def list_follow(mode: str = "zscore", metric: str = "yoy"):
    """그룹별 팔로우 + 최신월 + 파생지표·판정(D-140). 판정은 highlights와 같은 table()을 쓴다."""
    from pipeline.trade_metrics import table
    t = table(flow="export", mode=mode, metric=metric)
    by = {r["hs_code"]: r for r in t["rows"]}
    conn = get_connection()
    rows = conn.execute("SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 "
                        "ORDER BY group_label, hs_code").fetchall()
    out = []
    for r in rows:
        period, exp, yoy = _yoy(conn, r["hs_code"])
        m = by.get(r["hs_code"]) or {}
        out.append(FollowRow(hs_code=r["hs_code"], item_name=r["item_name"], group_label=r["group_label"],
                             latest_period=period, latest_export=exp, yoy_pct=yoy,
                             mom=m.get("mom"), qoq=m.get("qoq"), yoy3m=m.get("yoy3m"), z=m.get("z"),
                             flag=m.get("flag"), reason=m.get("reason"), contribution=m.get("contribution"),
                             nested_in=m.get("nested_in")))
    conn.close()
    return out


@router.get("/by-stock/{stock_code}", response_model=list[StockItem])
def by_stock(stock_code: str):
    """종목 도시에의 '수출 지표' 칩 — trade_beneficiaries를 거꾸로 읽는다(읽기 전용, LLM 0)."""
    from pipeline.trade_metrics import table
    conn = get_connection()
    rows = conn.execute(
        "SELECT b.hs_code, f.item_name, b.rel FROM trade_beneficiaries b "
        "JOIN trade_follow f ON f.hs_code=b.hs_code AND f.active=1 WHERE b.stock_code=? ORDER BY b.hs_code",
        (stock_code,)).fetchall()
    out = []
    if rows:
        by = {r["hs_code"]: r for r in table(flow="export")["rows"]}
        for r in rows:
            period, _, yoy = _yoy(conn, r["hs_code"])
            m = by.get(r["hs_code"]) or {}
            out.append(StockItem(hs_code=r["hs_code"], item_name=r["item_name"], rel=r["rel"], period=period,
                                 yoy_pct=yoy, flag=m.get("flag"), reason=m.get("reason")))
    conn.close()
    return out


@router.get("/highlights", response_model=Highlights)
def highlights(period: str | None = None, flow: str = "export", limit: int = 8, rank: str = "contribution",
               mode: str = "zscore", metric: str = "yoy", z_threshold: float | None = None, min_usd: float | None = None):
    """급등·급감 랭킹(D-140) — 기본 기여도 순. `/{hs_code}`보다 먼저 선언(경로 충돌 방지)."""
    from pipeline.trade_metrics import highlights as _hl
    return _hl(period, flow, limit=limit, rank=rank, mode=mode, metric=metric, z_threshold=z_threshold, min_usd=min_usd)


@router.get("/grid", response_model=TradeGrid)
def grid(months: int = Query(24, ge=24, le=60, description="24(2년) 또는 60(5년)")):
    """품목 벽(산업 › 수출입 품목 모니터) — 팔로우 품목(세목 제외) 전체의 월별 수출 시계열을 한 번에.
    원본은 한 번의 조회로 읽고(raw_series_all) 판정은 같은 원본으로 table()이 계산한다. 칸마다 `/{hs}`를 부르지 않는다."""
    if months not in (24, 60):
        raise HTTPException(422, "months는 24 또는 60")
    from pipeline.trade_metrics import _month_grid, raw_series_all, table
    conn = get_connection()
    try:
        raw = raw_series_all(conn)
        codes: dict[str, list[str]] = {}
        for r in conn.execute("SELECT DISTINCT b.hs_code, b.stock_code FROM trade_beneficiaries b "
                              "JOIN trade_follow f ON f.hs_code=b.hs_code AND f.active=1 "
                              "WHERE b.stock_code IS NOT NULL ORDER BY b.hs_code, b.stock_code"):
            codes.setdefault(r["hs_code"], []).append(r["stock_code"])
    finally:
        conn.close()
    t = table(flow="export", raw=raw)
    items = []
    for row in t["rows"]:
        if row.get("nested_in"):
            continue
        hs = row["hs_code"]
        by = {p["period"]: p["export_usd"] for p in raw.get(hs, [])}
        periods = _month_grid(min(by), max(by)) if by else []
        vals = [by.get(p) for p in periods]
        start = max(0, len(periods) - months)
        series = []
        for i in range(start, len(periods)):
            win = vals[i - 11:i + 1] if i >= 11 else []
            ma = sum(win) / 12 if len(win) == 12 and all(v is not None for v in win) else None
            series.append(GridPoint(period=periods[i], export_usd=vals[i], ma12=ma))
        last = next((i for i in range(len(vals) - 1, -1, -1) if vals[i] is not None), None)
        yoy = None
        if last is not None and last >= 12 and vals[last - 12]:
            yoy = round((vals[last] / vals[last - 12] - 1) * 100, 1)
        flag = row.get("flag") or "none"
        items.append(GridItem(hs_code=hs, item_name=row["item_name"], group_label=row["group_label"],
                              latest_period=periods[last] if last is not None else None,
                              latest_export=vals[last] if last is not None else None, yoy_pct=yoy,
                              mom=row.get("mom"), yoy3m=row.get("yoy3m"), contribution=row.get("contribution"),
                              z=row.get("z"), flag=flag if flag in ("surge", "plunge", "new") else "none",
                              stock_codes=codes.get(hs, []), series=series))
    return TradeGrid(period=t["period"], months=months, items=items)


@router.get("/{hs_code}/metrics")
def item_metrics(hs_code: str):
    """품목 월별 파생지표 시계열(수출·수입 각각 mom/yoy/qoq/yoy3m/z) — D-140."""
    from pipeline.trade_metrics import item_series
    return item_series(hs_code)


@router.get("/{hs_code}", response_model=Detail)
def detail(hs_code: str):
    conn = get_connection()
    item = conn.execute("SELECT item_name FROM trade_follow WHERE hs_code=?", (hs_code,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(404, "팔로우하지 않은 품목")
    series = [Stat(period=r["period"], export_usd=r["export_usd"], import_usd=r["import_usd"],
                   balance_usd=r["balance_usd"])
              for r in conn.execute("SELECT period, export_usd, import_usd, balance_usd FROM trade_stats "
                                    "WHERE hs_code=? ORDER BY period", (hs_code,)).fetchall()]
    bene = [Beneficiary(name=r["name"], stock_code=r["stock_code"], rel=r["rel"], reason=r["reason"],
                        rs=r["rs"], per=r["per"], mktcap=r["mktcap"], pos_52w=r["pos_52w"],
                        in_universe=bool(r["in_universe"]),
                        universe_groups=json.loads(r["universe_groups"] or "[]"))
            for r in conn.execute("SELECT * FROM trade_beneficiaries WHERE hs_code=? ORDER BY rel, rs DESC",
                                  (hs_code,)).fetchall()]
    conn.close()
    return Detail(hs_code=hs_code, item_name=item["item_name"], series=series, beneficiaries=bene)


@router.post("/{hs_code}/beneficiaries", response_model=list[Beneficiary])
def compute_bene(hs_code: str):
    """관련 종목 LLM 논리 지목 (멱등 재계산, ~수 분). apiComputeQuery."""
    from pipeline.trade import compute_beneficiaries
    compute_beneficiaries(hs_code)
    return detail(hs_code).beneficiaries


@router.post("/follow", status_code=201)
def upsert_follow(body: FollowReq):
    conn = get_connection()
    conn.execute(
        "INSERT INTO trade_follow (hs_code, item_name, group_label, active) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(hs_code) DO UPDATE SET active=excluded.active, "
        "item_name=COALESCE(excluded.item_name, trade_follow.item_name), "
        "group_label=COALESCE(excluded.group_label, trade_follow.group_label)",
        (body.hs_code, body.item_name or body.hs_code, body.group_label, 1 if body.active else 0))
    conn.commit()
    conn.close()
    return {"hs_code": body.hs_code, "active": body.active}


@router.post("/seed")
def seed():
    """기본 세트 + 개인 워치리스트 CSV(있으면) 시드."""
    from pipeline.trade import seed_default_follows, seed_watchlist
    return {"seeded_default": seed_default_follows(), **seed_watchlist()}

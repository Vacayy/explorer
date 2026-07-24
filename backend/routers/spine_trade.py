"""수출입(무역) 팔로우 API (docs/specs/trade-follow.md).

전용 페이지: 좌 팔로우 품목 → 우 수출입 추이 차트 + 관련 종목(LLM 논리 지목, 캐시).
"""
import json

from fastapi import APIRouter, HTTPException
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
def list_follow():
    conn = get_connection()
    rows = conn.execute("SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 "
                        "ORDER BY group_label, hs_code").fetchall()
    out = []
    for r in rows:
        period, exp, yoy = _yoy(conn, r["hs_code"])
        out.append(FollowRow(hs_code=r["hs_code"], item_name=r["item_name"], group_label=r["group_label"],
                             latest_period=period, latest_export=exp, yoy_pct=yoy))
    conn.close()
    return out


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
    from pipeline.trade import seed_default_follows
    return {"seeded": seed_default_follows()}

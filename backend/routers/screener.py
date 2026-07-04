"""Screener endpoint — filters stocks by KPI metrics."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from database import get_connection
from routers.kpi import get_kpi

router = APIRouter(prefix="/api/screener", tags=["screener"])

MCAP_SMALL = 300_000_000_000   # 300B won
MCAP_LARGE = 2_000_000_000_000  # 2T won

SORT_COLUMNS = {"market_cap", "per", "pbr", "op_margin", "roe", "revenue_growth"}


@router.get("")
def screener(
    per_max: Optional[float] = Query(None),
    pbr_max: Optional[float] = Query(None),
    opm_min: Optional[float] = Query(None),
    roe_min: Optional[float] = Query(None),
    rev_growth_min: Optional[float] = Query(None),
    mcap_tier: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
    limit: int = Query(100, ge=1, le=500),
):
    conn = get_connection()

    # Get all corp_codes that have financial data, then map to stock_code
    rows = conn.execute(
        """SELECT DISTINCT fs.corp_code, c.stock_code, c.corp_name
        FROM financial_statements fs
        JOIN companies c ON c.corp_code = fs.corp_code
        WHERE c.stock_code IS NOT NULL AND c.stock_code != ''"""
    ).fetchall()
    conn.close()

    filtered_from = len(rows)

    items = []
    for row in rows:
        stock_code = row["stock_code"]
        corp_name = row["corp_name"]

        try:
            kpi = get_kpi(stock_code)
        except HTTPException:
            continue
        except Exception:
            continue

        market_cap = kpi.get("market_cap")
        per = kpi.get("per")
        pbr = kpi.get("pbr")
        op_margin = kpi.get("op_margin")
        roe = kpi.get("roe")
        revenue_growth = kpi.get("revenue_growth")
        op_profit_growth = kpi.get("op_profit_growth")
        latest_close = kpi.get("close")

        # Apply filters
        if per_max is not None and (per is None or per > per_max):
            continue
        if pbr_max is not None and (pbr is None or pbr > pbr_max):
            continue
        if opm_min is not None and (op_margin is None or op_margin < opm_min):
            continue
        if roe_min is not None and (roe is None or roe < roe_min):
            continue
        if rev_growth_min is not None and (revenue_growth is None or revenue_growth < rev_growth_min):
            continue

        if mcap_tier and mcap_tier != "all":
            if market_cap is None:
                continue
            if mcap_tier == "small" and market_cap >= MCAP_SMALL:
                continue
            if mcap_tier == "mid" and not (MCAP_SMALL <= market_cap < MCAP_LARGE):
                continue
            if mcap_tier == "large" and market_cap < MCAP_LARGE:
                continue

        items.append({
            "stock_code": stock_code,
            "corp_name": corp_name,
            "market_cap": market_cap,
            "per": per,
            "pbr": pbr,
            "op_margin": op_margin,
            "revenue_growth": revenue_growth,
            "op_profit_growth": op_profit_growth,
            "roe": roe,
            "latest_close": latest_close,
        })

    # Sort
    if sort and sort in SORT_COLUMNS:
        reverse = (sort_dir or "desc").lower() != "asc"
        items.sort(key=lambda x: (x[sort] is None, x[sort] or 0), reverse=reverse)

    total = len(items)
    items = items[:limit]

    return {"items": items, "total": total, "filtered_from": filtered_from}

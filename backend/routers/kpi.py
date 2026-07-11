"""KPI summary endpoint — aggregates price, valuation, and financial metrics for Hero cards."""
from fastapi import APIRouter, HTTPException
from database import get_connection
from services.dart_service import _corp_code_for_stock, _normalize_account_name, _parse_amount, SJ_DIV_QUERY

router = APIRouter(prefix="/api/kpi", tags=["kpi"])


@router.get("/{stock_code}")
def get_kpi(stock_code: str):
    """Return key performance indicators for a single stock.

    Combines: latest price, market cap, PER, PBR, operating margin, ROE, revenue growth.
    All computed from cached local data (no external API calls).
    """
    corp_code = _corp_code_for_stock(stock_code)
    if not corp_code:
        raise HTTPException(404, "Company not found")

    conn = get_connection()

    # 1. Latest price + market cap
    price_row = conn.execute(
        """SELECT close, market_cap, trade_date
        FROM stock_prices WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1""",
        (stock_code,),
    ).fetchone()

    prev_price_row = conn.execute(
        """SELECT close FROM stock_prices WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1 OFFSET 1""",
        (stock_code,),
    ).fetchone()

    latest_close = price_row["close"] if price_row else None
    prev_close = prev_price_row["close"] if prev_price_row else None
    market_cap = price_row["market_cap"] if price_row else None
    price_change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if latest_close and prev_close and prev_close != 0 else None

    # 2. Latest fundamentals (PER, PBR)
    fund_row = conn.execute(
        """SELECT per, pbr, eps, bps FROM fundamentals
        WHERE stock_code = ? AND (per IS NOT NULL OR pbr IS NOT NULL)
        ORDER BY trade_date DESC LIMIT 1""",
        (stock_code,),
    ).fetchone()

    per = fund_row["per"] if fund_row else None
    pbr = fund_row["pbr"] if fund_row else None

    # 3. Financial metrics from latest annual report
    # Get latest 2 years of IS data for YoY calculation
    sj_values = SJ_DIV_QUERY["IS"]
    placeholders = ",".join("?" for _ in sj_values)

    is_rows = conn.execute(
        f"""SELECT bsns_year, account_nm, thstrm_amount
        FROM financial_statements
        WHERE corp_code = ? AND fs_div IN ('CFS', 'OFS') AND sj_div IN ({placeholders})
          AND reprt_code = '11011'
        ORDER BY bsns_year DESC""",
        (corp_code, *sj_values),
    ).fetchall()

    # Also get BS for equity (ROE calculation)
    bs_rows = conn.execute(
        """SELECT bsns_year, account_nm, thstrm_amount
        FROM financial_statements
        WHERE corp_code = ? AND fs_div IN ('CFS', 'OFS') AND sj_div = 'BS'
          AND reprt_code = '11011'
        ORDER BY bsns_year DESC""",
        (corp_code,),
    ).fetchall()

    conn.close()

    # Parse IS data by year
    is_by_year: dict[int, dict[str, int | None]] = {}
    for r in is_rows:
        year = r["bsns_year"]
        name = _normalize_account_name(r["account_nm"])
        if year not in is_by_year:
            is_by_year[year] = {}
        if name not in is_by_year[year]:
            is_by_year[year][name] = _parse_amount(r["thstrm_amount"])

    bs_by_year: dict[int, dict[str, int | None]] = {}
    for r in bs_rows:
        year = r["bsns_year"]
        name = r["account_nm"]
        if year not in bs_by_year:
            bs_by_year[year] = {}
        if name not in bs_by_year[year]:
            bs_by_year[year][name] = _parse_amount(r["thstrm_amount"])

    sorted_years = sorted(is_by_year.keys(), reverse=True)
    latest_year = sorted_years[0] if sorted_years else None
    prev_year = sorted_years[1] if len(sorted_years) > 1 else None

    # Calculate metrics
    revenue = _get_metric(is_by_year, latest_year, ["매출액", "매출", "영업수익"])
    prev_revenue = _get_metric(is_by_year, prev_year, ["매출액", "매출", "영업수익"])
    op_profit = _get_metric(is_by_year, latest_year, ["영업이익"])
    prev_op_profit = _get_metric(is_by_year, prev_year, ["영업이익"])
    net_income = _get_metric(is_by_year, latest_year, ["당기순이익"])
    equity = _get_metric(bs_by_year, latest_year, ["자본총계"])

    op_margin = round(op_profit / revenue * 100, 1) if revenue and op_profit else None
    prev_op_margin = round(prev_op_profit / prev_revenue * 100, 1) if prev_revenue and prev_op_profit else None
    op_margin_change = round(op_margin - prev_op_margin, 1) if op_margin is not None and prev_op_margin is not None else None

    roe = round(net_income / equity * 100, 1) if net_income and equity and equity != 0 else None
    prev_net = _get_metric(is_by_year, prev_year, ["당기순이익"])
    prev_eq = _get_metric(bs_by_year, prev_year, ["자본총계"])
    prev_roe = round(prev_net / prev_eq * 100, 1) if prev_net and prev_eq and prev_eq != 0 else None
    roe_change = round(roe - prev_roe, 1) if roe is not None and prev_roe is not None else None

    rev_growth = round((revenue - prev_revenue) / abs(prev_revenue) * 100, 1) if revenue and prev_revenue and prev_revenue != 0 else None
    op_growth = round((op_profit - prev_op_profit) / abs(prev_op_profit) * 100, 1) if op_profit and prev_op_profit and prev_op_profit != 0 else None

    # Self-calculated PER/PBR if fundamentals table is empty
    if per is None and net_income and market_cap and net_income > 0:
        per = round(market_cap / net_income, 1)
    if pbr is None and equity and market_cap and equity > 0:
        pbr = round(market_cap / equity, 2)

    # Forward estimates from consensus
    conn2 = get_connection()
    fwd_row = conn2.execute(
        """SELECT eps_est, per_est, target_price, fiscal_year FROM consensus
           WHERE stock_code = ? ORDER BY fiscal_year DESC LIMIT 1""",
        (stock_code,),
    ).fetchone()
    conn2.close()

    fwd_per = fwd_row["per_est"] if fwd_row else None
    fwd_eps = fwd_row["eps_est"] if fwd_row else None
    target_price_consensus = fwd_row["target_price"] if fwd_row else None

    # Derive fwd_per from fwd_eps and current price if not directly available
    if fwd_per is None and fwd_eps and fwd_eps > 0 and latest_close:
        fwd_per = round(latest_close / fwd_eps, 1)

    return {
        "stock_code": stock_code,
        "latest_year": latest_year,
        "close": latest_close,
        "price_change_pct": price_change_pct,
        "market_cap": market_cap,
        "per": per,
        "pbr": pbr,
        "op_margin": op_margin,
        "op_margin_change": op_margin_change,
        "roe": roe,
        "roe_change": roe_change,
        "revenue": revenue,
        "revenue_growth": rev_growth,
        "op_profit": op_profit,
        "op_profit_growth": op_growth,
        "net_income": net_income,
        "fwd_per": fwd_per,
        "fwd_fiscal_year": fwd_row["fiscal_year"] if fwd_row else None,  # 예: 2026E — 라벨 정직성
        "fwd_eps": fwd_eps,
        "target_price_consensus": target_price_consensus,
    }


def _get_metric(data: dict, year: int | None, candidates: list[str]) -> int | None:
    if year is None or year not in data:
        return None
    for c in candidates:
        if c in data[year] and data[year][c] is not None:
            return data[year][c]
    return None

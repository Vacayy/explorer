from fastapi import APIRouter, HTTPException, Query
from database import get_connection
from services.krx_service import _fetch_and_store_prices
from services.dart_service import _normalize_account_name, _parse_amount, SJ_DIV_QUERY
from pydantic import BaseModel

router = APIRouter(prefix="/api/industries", tags=["industries"])


def _get_metric(data: dict, year: int | None, candidates: list[str]) -> int | None:
    if year is None or year not in data:
        return None
    for c in candidates:
        if c in data[year] and data[year][c] is not None:
            return data[year][c]
    return None


@router.get("/")
def list_groups():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, description FROM industry_groups ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/{group_id}")
def get_group_detail(group_id: int):
    conn = get_connection()
    group = conn.execute(
        "SELECT id, name, description FROM industry_groups WHERE id = ?", (group_id,)
    ).fetchone()
    if not group:
        conn.close()
        raise HTTPException(404, "Industry group not found")

    members = conn.execute(
        """
        SELECT im.id, im.stock_code, im.category, c.corp_name,
               (SELECT sp.close FROM stock_prices sp
                WHERE sp.stock_code = im.stock_code
                ORDER BY sp.trade_date DESC LIMIT 1) as latest_close,
               (SELECT sp.market_cap FROM stock_prices sp
                WHERE sp.stock_code = im.stock_code AND sp.market_cap IS NOT NULL
                ORDER BY sp.trade_date DESC LIMIT 1) as latest_market_cap
        FROM industry_members im
        JOIN companies c ON c.stock_code = im.stock_code
        WHERE im.group_id = ?
        ORDER BY im.category, im.sort_order
        """,
        (group_id,),
    ).fetchall()

    # Batch-fetch financial metrics to avoid N+1 queries
    member_dicts = [dict(m) for m in members]
    stock_codes = [d["stock_code"] for d in member_dicts]

    if not stock_codes:
        conn.close()
        return {"group": dict(group), "members": []}

    sc_placeholders = ",".join("?" for _ in stock_codes)

    # 1. Map stock_code -> corp_code
    corp_rows = conn.execute(
        f"SELECT stock_code, corp_code FROM companies WHERE stock_code IN ({sc_placeholders})",
        stock_codes,
    ).fetchall()
    sc_to_corp = {r["stock_code"]: r["corp_code"] for r in corp_rows}
    corp_codes = list(set(sc_to_corp.values()))

    # 2. Batch fundamentals (PER, PBR) — latest per stock_code
    fund_rows = conn.execute(
        f"""SELECT stock_code, per, pbr FROM fundamentals
        WHERE stock_code IN ({sc_placeholders}) AND (per IS NOT NULL OR pbr IS NOT NULL)
        ORDER BY trade_date DESC""",
        stock_codes,
    ).fetchall()
    fund_by_sc: dict[str, dict] = {}
    for r in fund_rows:
        sc = r["stock_code"]
        if sc not in fund_by_sc:
            fund_by_sc[sc] = {"per": r["per"], "pbr": r["pbr"]}

    # 3. Batch IS + BS financial statements for all corp_codes
    is_by_corp: dict[str, dict[int, dict[str, int | None]]] = {}
    bs_by_corp: dict[str, dict[int, dict[str, int | None]]] = {}

    if corp_codes:
        cc_placeholders = ",".join("?" for _ in corp_codes)
        sj_values = SJ_DIV_QUERY["IS"]
        sj_placeholders = ",".join("?" for _ in sj_values)

        is_rows = conn.execute(
            f"""SELECT corp_code, bsns_year, account_nm, thstrm_amount
            FROM financial_statements
            WHERE corp_code IN ({cc_placeholders}) AND fs_div IN ('CFS', 'OFS')
              AND sj_div IN ({sj_placeholders}) AND reprt_code = '11011'
            ORDER BY bsns_year DESC""",
            (*corp_codes, *sj_values),
        ).fetchall()

        for r in is_rows:
            cc = r["corp_code"]
            year = r["bsns_year"]
            name = _normalize_account_name(r["account_nm"])
            is_by_corp.setdefault(cc, {}).setdefault(year, {})
            if name not in is_by_corp[cc][year]:
                is_by_corp[cc][year][name] = _parse_amount(r["thstrm_amount"])

        bs_rows = conn.execute(
            f"""SELECT corp_code, bsns_year, account_nm, thstrm_amount
            FROM financial_statements
            WHERE corp_code IN ({cc_placeholders}) AND fs_div IN ('CFS', 'OFS')
              AND sj_div = 'BS' AND reprt_code = '11011'
            ORDER BY bsns_year DESC""",
            corp_codes,
        ).fetchall()

        for r in bs_rows:
            cc = r["corp_code"]
            year = r["bsns_year"]
            name = r["account_nm"]
            bs_by_corp.setdefault(cc, {}).setdefault(year, {})
            if name not in bs_by_corp[cc][year]:
                bs_by_corp[cc][year][name] = _parse_amount(r["thstrm_amount"])

    conn.close()

    # 4. Compute per-member metrics
    enriched = []
    for d in member_dicts:
        sc = d["stock_code"]
        cc = sc_to_corp.get(sc)
        fund = fund_by_sc.get(sc, {})
        d["per"] = fund.get("per")
        d["pbr"] = fund.get("pbr")

        is_data = is_by_corp.get(cc, {}) if cc else {}
        bs_data = bs_by_corp.get(cc, {}) if cc else {}

        sorted_years = sorted(is_data.keys(), reverse=True)
        latest_year = sorted_years[0] if sorted_years else None
        prev_year = sorted_years[1] if len(sorted_years) > 1 else None

        revenue = _get_metric(is_data, latest_year, ["매출액", "매출", "영업수익"])
        prev_revenue = _get_metric(is_data, prev_year, ["매출액", "매출", "영업수익"])
        op_profit = _get_metric(is_data, latest_year, ["영업이익"])
        prev_op_profit = _get_metric(is_data, prev_year, ["영업이익"])
        net_income = _get_metric(is_data, latest_year, ["당기순이익"])
        equity = _get_metric(bs_data, latest_year, ["자본총계"])

        d["op_margin"] = round(op_profit / revenue * 100, 1) if revenue and op_profit else None
        d["roe"] = round(net_income / equity * 100, 1) if net_income and equity and equity != 0 else None
        d["revenue_growth"] = round((revenue - prev_revenue) / abs(prev_revenue) * 100, 1) if revenue and prev_revenue and prev_revenue != 0 else None
        d["op_profit_growth"] = round((op_profit - prev_op_profit) / abs(prev_op_profit) * 100, 1) if op_profit and prev_op_profit and prev_op_profit != 0 else None

        # Self-calculated PER/PBR fallback
        market_cap = d.get("latest_market_cap")
        if d["per"] is None and net_income and market_cap and net_income > 0:
            d["per"] = round(market_cap / net_income, 1)
        if d["pbr"] is None and equity and market_cap and equity > 0:
            d["pbr"] = round(market_cap / equity, 2)

        enriched.append(d)

    return {
        "group": dict(group),
        "members": enriched,
    }


@router.post("/{group_id}/fetch-prices")
def fetch_prices_for_group(group_id: int):
    """Batch fetch latest prices and market caps for all members in a group."""
    conn = get_connection()
    members = conn.execute(
        "SELECT im.stock_code FROM industry_members im WHERE im.group_id = ?",
        (group_id,),
    ).fetchall()
    conn.close()

    if not members:
        raise HTTPException(404, "No members in group")

    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y%m%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

    fetched = 0
    errors = []
    for row in members:
        stock_code = row["stock_code"]
        try:
            _fetch_single_latest(stock_code, week_ago, today)
            fetched += 1
        except Exception as e:
            errors.append(f"{stock_code}: {e}")

    return {"fetched": fetched, "errors": errors[:5]}


def _fetch_single_latest(stock_code: str, from_date: str, to_date: str):
    """Fetch latest OHLCV + market cap for a single stock using yfinance."""
    from services.krx_service import _fetch_and_store_prices
    _fetch_and_store_prices(stock_code, from_date, to_date)
    return


def _fetch_single_latest_DISABLED(stock_code: str, from_date: str, to_date: str):
    """OLD pykrx version — disabled due to KRX connectivity issues."""
    from pykrx import stock as krx
    from database import get_connection

    try:
        ohlcv = krx.get_market_ohlcv_by_date(from_date, to_date, stock_code, adjusted=True)
    except Exception:
        return

    if ohlcv is None or ohlcv.empty:
        return

    mcap_map = _fetch_yfinance_marketcap(stock_code, from_date, to_date)

    conn = get_connection()
    for date_idx in ohlcv.index:
        d = date_idx.strftime("%Y-%m-%d")
        row = ohlcv.loc[date_idx]
        mcap = mcap_map.get(d)
        conn.execute(
            """
            INSERT OR REPLACE INTO stock_prices
            (stock_code, trade_date, open, high, low, close, volume, market_cap, shares)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stock_code, d,
                int(row.get("시가", 0)) or None,
                int(row.get("고가", 0)) or None,
                int(row.get("저가", 0)) or None,
                int(row.get("종가", 0)) or None,
                int(row.get("거래량", 0)) or None,
                mcap, None,
            ),
        )
    conn.commit()
    conn.close()


class MemberAdd(BaseModel):
    stock_code: str
    category: str


@router.post("/{group_id}/members")
def add_member(group_id: int, body: MemberAdd):
    conn = get_connection()
    exists = conn.execute("SELECT id FROM industry_groups WHERE id = ?", (group_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "Group not found")

    conn.execute(
        "INSERT OR REPLACE INTO industry_members (group_id, stock_code, category) VALUES (?, ?, ?)",
        (group_id, body.stock_code, body.category),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/members/{member_id}")
def remove_member(member_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM industry_members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

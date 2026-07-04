"""DART OpenAPI wrapper with SQLite caching."""
import re
from datetime import datetime
from config import DART_API_KEY, CACHE_TTL_FINANCIALS, CACHE_TTL_DISCLOSURES
from database import get_connection
from services.cache_service import is_cached, set_cache

_dart = None


def _get_dart():
    global _dart
    if _dart is None:
        import OpenDartReader
        _dart = OpenDartReader(DART_API_KEY)
    return _dart

# DART report codes
REPRT_ANNUAL = "11011"      # 사업보고서 (annual)
REPRT_Q1 = "11013"          # 1분기보고서
REPRT_H1 = "11012"          # 반기보고서
REPRT_Q3 = "11014"          # 3분기보고서

REPRT_CODES_QUARTERLY = [REPRT_Q1, REPRT_H1, REPRT_Q3, REPRT_ANNUAL]

# Map user-facing sj_div to actual DART sj_div values in DB.
SJ_DIV_QUERY = {
    "IS": ("CIS", "IS"),
    "BS": ("BS",),
    "CF": ("CF",),
}

# Flow statements (IS, CF) are cumulative in DART → need quarterly decomposition
# Stock statements (BS) are point-in-time → no decomposition
CUMULATIVE_STATEMENTS = {"IS", "CF"}


def _parse_amount(val) -> int | None:
    if val is None or str(val).strip() in ("", "-", "nan"):
        return None
    s = re.sub(r"[,\s]", "", str(val))
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _corp_code_for_stock(stock_code: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT corp_code FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    conn.close()
    return row["corp_code"] if row else None


def fetch_financial_statements(
    stock_code: str,
    sj_div: str = "IS",
    period: str = "annual",
    years: int = 5,
    fs_div: str = "CFS",
) -> dict:
    corp_code = _corp_code_for_stock(stock_code)
    if not corp_code:
        return {"periods": [], "rows": [], "key_metrics": {}, "sj_div": sj_div, "fs_div": fs_div, "period_type": period}

    current_year = datetime.now().year
    start_year = current_year - years

    # Always fetch all report codes so quarterly decomposition works
    reprt_codes = REPRT_CODES_QUARTERLY

    # Fetch both CFS and OFS — some companies only have OFS (no subsidiaries)
    fs_divs_to_fetch = [fs_div]
    if fs_div == "CFS":
        fs_divs_to_fetch.append("OFS")  # fallback

    for fd in fs_divs_to_fetch:
        for year in range(start_year, current_year + 1):
            for rc in reprt_codes:
                cache_key = f"finstate:{corp_code}:{year}:{rc}:{fd}"
                if is_cached(cache_key):
                    continue
                try:
                    df = _get_dart().finstate_all(corp_code, year, rc, fs_div=fd)
                    if df is not None and not df.empty:
                        _store_financial_df(corp_code, year, rc, fd, df)
                    set_cache(cache_key, CACHE_TTL_FINANCIALS)
                except Exception:
                    set_cache(cache_key, CACHE_TTL_FINANCIALS)

    # Try CFS first; if empty, fall back to OFS
    result = _build_financial_response(corp_code, sj_div, period, start_year, current_year, fs_div)
    if not result["rows"] and fs_div == "CFS":
        result = _build_financial_response(corp_code, sj_div, period, start_year, current_year, "OFS")
        result["fs_div"] = "OFS"
    return result


def _store_financial_df(corp_code: str, year: int, reprt_code: str, fs_div: str, df):
    conn = get_connection()
    for _, row in df.iterrows():
        sj = row.get("sj_div", "")
        account = row.get("account_nm", "")
        if not sj or not account:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO financial_statements
            (corp_code, bsns_year, reprt_code, fs_div, sj_div, account_nm, thstrm_amount, frmtrm_amount, bfefrmtrm_amount, ord)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                corp_code, year, reprt_code, fs_div,
                sj, account,
                str(row.get("thstrm_amount", "")),
                str(row.get("frmtrm_amount", "")),
                str(row.get("bfefrmtrm_amount", "")),
                row.get("ord", 0),
            ),
        )
    conn.commit()
    conn.close()


def _period_label(year: int, reprt_code: str) -> str:
    suffix = {"11011": ".12", "11013": ".03", "11012": ".06", "11014": ".09"}
    yy = str(year)[2:]
    return f"{yy}{suffix.get(reprt_code, '')}"


def _build_financial_response(
    corp_code: str, sj_div: str, period: str, start_year: int, current_year: int, fs_div: str
) -> dict:
    conn = get_connection()

    sj_values = SJ_DIV_QUERY.get(sj_div, (sj_div,))
    placeholders = ",".join("?" for _ in sj_values)

    # Always fetch all report codes for quarterly decomposition
    rows = conn.execute(
        f"""
        SELECT bsns_year, reprt_code, account_nm, thstrm_amount, ord
        FROM financial_statements
        WHERE corp_code = ? AND fs_div = ? AND sj_div IN ({placeholders})
          AND bsns_year >= ? AND bsns_year <= ?
        ORDER BY ord, account_nm, bsns_year, reprt_code
        """,
        (corp_code, fs_div, *sj_values, start_year, current_year),
    ).fetchall()
    conn.close()

    if not rows:
        return {"periods": [], "rows": [], "key_metrics": {}, "sj_div": sj_div, "fs_div": fs_div, "period_type": period}

    # Group by account: raw cumulative data from DART
    # Normalize account names so "영업이익" and "영업이익(손실)" merge into one row
    accounts_raw: dict[str, dict] = {}
    for r in rows:
        account = _normalize_account_name(r["account_nm"])
        if account not in accounts_raw:
            accounts_raw[account] = {"ord": r["ord"] or 0, "data": {}}
        key = (r["bsns_year"], r["reprt_code"])
        # Don't overwrite if we already have a value for this period
        if accounts_raw[account]["data"].get(key) is None:
            accounts_raw[account]["data"][key] = _parse_amount(r["thstrm_amount"])

    # Decompose to individual quarters for flow statements (IS, CF)
    is_cumulative = sj_div in CUMULATIVE_STATEMENTS
    accounts_decomposed: dict[str, dict] = {}
    for account_nm, acct in accounts_raw.items():
        accounts_decomposed[account_nm] = {"ord": acct["ord"], "data": {}}
        for year in range(start_year, current_year + 1):
            q1_val = acct["data"].get((year, REPRT_Q1))
            h1_val = acct["data"].get((year, REPRT_H1))
            q3_val = acct["data"].get((year, REPRT_Q3))
            ann_val = acct["data"].get((year, REPRT_ANNUAL))

            if is_cumulative:
                # Decompose cumulative → individual quarter
                q1 = q1_val
                q2 = _subtract(h1_val, q1_val)
                q3 = _subtract(q3_val, h1_val)
                q4 = _subtract(ann_val, q3_val)
            else:
                # BS: point-in-time, use raw values
                q1 = q1_val
                q2 = h1_val
                q3 = q3_val
                q4 = ann_val

            accounts_decomposed[account_nm]["data"][(year, REPRT_Q1)] = q1
            accounts_decomposed[account_nm]["data"][(year, REPRT_H1)] = q2
            accounts_decomposed[account_nm]["data"][(year, REPRT_Q3)] = q3
            accounts_decomposed[account_nm]["data"][(year, REPRT_ANNUAL)] = q4

    # Determine which data to use based on period type
    if period == "annual":
        # For annual: sum the 4 quarters (for IS/CF) or use annual value (for BS)
        accounts: dict[str, dict] = {}
        for account_nm, acct in accounts_raw.items():
            accounts[account_nm] = {"ord": acct["ord"], "data": {}}
            for year in range(start_year, current_year + 1):
                if is_cumulative:
                    # Annual report value is the full year (already cumulative)
                    val = acct["data"].get((year, REPRT_ANNUAL))
                else:
                    val = acct["data"].get((year, REPRT_ANNUAL))
                accounts[account_nm]["data"][(year, REPRT_ANNUAL)] = val
        period_keys = [(y, REPRT_ANNUAL) for y in range(start_year, current_year + 1)]
    else:
        # Quarterly: use decomposed values
        accounts = accounts_decomposed
        period_keys = []
        for y in range(start_year, current_year + 1):
            for rc in REPRT_CODES_QUARTERLY:
                period_keys.append((y, rc))

    # Filter to periods with data
    period_keys = [pk for pk in period_keys if any(
        acct["data"].get(pk) is not None for acct in accounts.values()
    )]

    periods = [_period_label(y, rc) for y, rc in period_keys]

    # Build rows with YoY
    result_rows = []
    sorted_accounts = sorted(accounts.items(), key=lambda x: x[1]["ord"])

    for account_nm, acct_data in sorted_accounts:
        values = []
        for pk in period_keys:
            v = acct_data["data"].get(pk)
            values.append(str(v) if v is not None else None)

        yoy: list[float | None] = []
        if period == "annual":
            for i, pk in enumerate(period_keys):
                if i == 0:
                    yoy.append(None)
                    continue
                cur = acct_data["data"].get(pk)
                prev = acct_data["data"].get(period_keys[i - 1])
                if cur is not None and prev is not None and prev != 0:
                    yoy.append(round((cur - prev) / abs(prev) * 100, 1))
                else:
                    yoy.append(None)
        else:
            # Quarterly YoY: compare same quarter previous year
            for _i, (y, rc) in enumerate(period_keys):
                prev_key = (y - 1, rc)
                cur = acct_data["data"].get((y, rc))
                prev = acct_data["data"].get(prev_key)
                if cur is not None and prev is not None and prev != 0:
                    yoy.append(round((cur - prev) / abs(prev) * 100, 1))
                else:
                    yoy.append(None)

        result_rows.append({
            "account_nm": account_nm,
            "values": values,
            "yoy": yoy,
        })

    # key_metrics
    key_metrics = _build_key_metrics(sj_div, result_rows)

    return {
        "periods": periods,
        "rows": result_rows,
        "key_metrics": key_metrics,
        "sj_div": sj_div,
        "fs_div": fs_div,
        "period_type": period,
    }


# Normalize variant DART account names to canonical forms
_ACCOUNT_NORMALIZE = {
    "영업이익(손실)": "영업이익",
    "당기순이익(손실)": "당기순이익",
    "당기순손익": "당기순이익",
    "분기순이익(손실)": "당기순이익",
    "분기순이익": "당기순이익",
    "반기순이익(손실)": "당기순이익",
    "반기순이익": "당기순이익",
    "법인세비용차감전순이익(손실)": "법인세비용차감전순이익",
    "법인세비용차감전계속영업손익": "법인세비용차감전순이익",
    "법인세비용차감전계속영업이익(손실)": "법인세비용차감전순이익",
    "수익(매출액)": "매출액",
    "영업손익": "영업이익",
    "영업수익": "매출액",
    "지배기업의 소유주에게 귀속되는 당기순이익(손실)": "지배기업순이익",
}


def _normalize_account_name(name: str) -> str:
    return _ACCOUNT_NORMALIZE.get(name, name)


def _subtract(a: int | None, b: int | None) -> int | None:
    """Subtract b from a, handling None."""
    if a is None:
        return None
    if b is None:
        return a  # If prior cumulative is missing, assume it's the standalone value
    return a - b


def _build_key_metrics(sj_div: str, result_rows: list[dict]) -> dict:
    mapping: dict[str, list[str]] = {}
    if sj_div == "IS":
        # Account names are already normalized by _normalize_account_name
        mapping = {
            "매출액": ["매출액", "매출"],
            "매출원가": ["매출원가"],
            "매출총이익": ["매출총이익"],
            "영업이익": ["영업이익"],
            "당기순이익": ["당기순이익"],
            "법인세비용차감전순이익": ["법인세비용차감전순이익"],
        }
    elif sj_div == "BS":
        mapping = {
            "자산총계": ["자산총계"],
            "유동자산": ["유동자산"],
            "비유동자산": ["비유동자산"],
            "부채총계": ["부채총계"],
            "유동부채": ["유동부채"],
            "비유동부채": ["비유동부채"],
            "자본총계": ["자본총계"],
        }
    elif sj_div == "CF":
        mapping = {
            "영업활동현금흐름": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
            "투자활동현금흐름": ["투자활동현금흐름", "투자활동으로인한현금흐름"],
            "재무활동현금흐름": ["재무활동현금흐름", "재무활동으로인한현금흐름"],
        }
    return _extract_key_metrics(result_rows, mapping)


def _extract_key_metrics(result_rows: list[dict], mapping: dict[str, list[str]]) -> dict:
    metrics = {}
    for metric_name, candidates in mapping.items():
        matched_row = None
        for c in candidates:
            for row in result_rows:
                if row["account_nm"] == c:
                    matched_row = row
                    break
            if matched_row:
                break
        if matched_row:
            metrics[metric_name] = {
                "values": matched_row["values"],
                "yoy": matched_row["yoy"],
                "account_nm": matched_row["account_nm"],
            }
    return metrics


def fetch_disclosures(
    stock_code: str,
    kind: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    corp_code = _corp_code_for_stock(stock_code)
    if not corp_code:
        return {"items": [], "total": 0}

    if not start:
        start = f"{datetime.now().year - 1}0101"
    if not end:
        end = datetime.now().strftime("%Y%m%d")

    cache_key = f"disc:{corp_code}:{start}:{end}:{kind or 'all'}"

    if not is_cached(cache_key):
        try:
            df = _get_dart().list(corp_code, start=start, end=end, kind=kind or "")
            if df is not None and not df.empty:
                conn = get_connection()
                for _, row in df.iterrows():
                    rcp_no = str(row.get("rcept_no", ""))
                    if not rcp_no:
                        continue
                    dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}"
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO disclosures
                        (rcp_no, corp_code, corp_name, report_nm, rcept_dt, flr_nm, rm, kind, dart_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rcp_no, corp_code,
                            str(row.get("corp_name", "")),
                            str(row.get("report_nm", "")),
                            str(row.get("rcept_dt", "")),
                            str(row.get("flr_nm", "")),
                            str(row.get("rm", "")),
                            kind or "",
                            dart_url,
                        ),
                    )
                conn.commit()
                conn.close()
        except Exception:
            pass
        set_cache(cache_key, CACHE_TTL_DISCLOSURES)

    conn = get_connection()
    where = "WHERE corp_code = ? AND rcept_dt >= ? AND rcept_dt <= ?"
    params: list = [corp_code, start, end]

    if kind:
        where += " AND kind = ?"
        params.append(kind)

    total_row = conn.execute(
        f"SELECT COUNT(*) as cnt FROM disclosures {where}", params
    ).fetchone()
    total = total_row["cnt"] if total_row else 0

    offset = (page - 1) * size
    items = conn.execute(
        f"""
        SELECT rcp_no, corp_name, report_nm, rcept_dt, flr_nm, rm, dart_url
        FROM disclosures {where}
        ORDER BY rcept_dt DESC
        LIMIT ? OFFSET ?
        """,
        params + [size, offset],
    ).fetchall()
    conn.close()

    return {
        "items": [dict(r) for r in items],
        "total": total,
    }

from fastapi import APIRouter, Query
from database import get_connection
from datetime import date, timedelta

router = APIRouter(prefix="/api/signals", tags=["signals"])

KIND_TO_TYPE = {"B": "contract", "D": "insider"}


@router.get("")
def get_signals(
    stock_codes: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
    type: str = Query("all"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
):
    conn = get_connection()

    # Resolve stock_codes
    if stock_codes:
        codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
    else:
        rows = conn.execute("SELECT stock_code FROM watchlist").fetchall()
        codes = [r["stock_code"] for r in rows]

    if not codes:
        conn.close()
        return {"items": [], "total": 0}

    # Get watchlist set for in_watchlist flag
    wl_rows = conn.execute("SELECT stock_code FROM watchlist").fetchall()
    watchlist_set = {r["stock_code"] for r in wl_rows}

    since = (date.today() - timedelta(days=days)).strftime("%Y%m%d")

    placeholders = ",".join("?" * len(codes))

    # Filter by type via kind
    kind_filter = ""
    if type == "contract":
        kind_filter = "AND d.kind = 'B'"
    elif type == "insider":
        kind_filter = "AND d.kind = 'D'"
    elif type == "disclosure":
        kind_filter = "AND (d.kind IS NULL OR (d.kind != 'B' AND d.kind != 'D'))"

    base_sql = f"""
        FROM disclosures d
        JOIN companies c ON c.corp_code = d.corp_code
        WHERE c.stock_code IN ({placeholders})
          AND d.rcept_dt >= ?
          {kind_filter}
    """

    total = conn.execute(
        f"SELECT COUNT(*) {base_sql}", codes + [since]
    ).fetchone()[0]

    offset = (page - 1) * size
    rows = conn.execute(
        f"""
        SELECT d.rcp_no, d.kind, d.corp_name, d.report_nm, d.rcept_dt, d.dart_url,
               c.stock_code
        {base_sql}
        ORDER BY d.rcept_dt DESC
        LIMIT ? OFFSET ?
        """,
        codes + [since, size, offset],
    ).fetchall()

    conn.close()

    items = []
    for r in rows:
        kind = r["kind"]
        signal_type = KIND_TO_TYPE.get(kind, "disclosure")
        rcept_dt = r["rcept_dt"] or ""
        # rcept_dt is stored as YYYYMMDD
        if len(rcept_dt) == 8:
            date_str = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"
        else:
            date_str = rcept_dt

        items.append(
            {
                "type": signal_type,
                "stock_code": r["stock_code"],
                "corp_name": r["corp_name"],
                "title": r["report_nm"],
                "date": date_str,
                "url": r["dart_url"],
                "in_watchlist": r["stock_code"] in watchlist_set,
            }
        )

    return {"items": items, "total": total}

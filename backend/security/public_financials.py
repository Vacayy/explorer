"""Stored-only financial projection; no collectors, private tables or DB writes."""
from datetime import datetime
from pathlib import Path
import sqlite3

from fastapi import HTTPException
from config import DB_PATH
from services.dart_service import _build_financial_response, SJ_DIV_QUERY

COLUMNS = {
    'companies': {'stock_code', 'corp_code'},
    'financial_statements': {'corp_code', 'fs_div', 'sj_div', 'bsns_year',
                             'reprt_code', 'account_nm', 'thstrm_amount', 'ord'},
}


def _authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if (action == sqlite3.SQLITE_READ and database == 'main'
            and table in COLUMNS and column in COLUMNS[table]):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def financial_connection(path: Path | None = None):
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        conn.set_authorizer(_authorize)
        return conn
    except Exception:
        conn.close()
        raise


def stored_financials(stock_code, sj_div, period, years, fs_div):
    conn = financial_connection()
    try:
        company = conn.execute('SELECT corp_code FROM companies WHERE stock_code = ?', (stock_code,)).fetchone()
        if company is None:
            raise HTTPException(404, 'Company not found')
        year = datetime.now().year
        if fs_div == 'CFS':
            sj_values = SJ_DIV_QUERY.get(sj_div, (sj_div,))
            placeholders = ','.join('?' for _ in sj_values)
            present = conn.execute(
                f"SELECT corp_code FROM financial_statements WHERE corp_code=? AND fs_div='CFS' "
                f"AND sj_div IN ({placeholders}) AND bsns_year>=? AND bsns_year<=? LIMIT 1",
                (company['corp_code'] or '', *sj_values, year - years, year),
            ).fetchone()
            # Incomplete CFS periods are not permission to switch accounting scope.
            if present is None:
                fs_div = 'OFS'
        return _build_financial_response(company['corp_code'] or '', sj_div, period,
                                         year - years, year, fs_div, connection=conn)

    finally:
        conn.close()

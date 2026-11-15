"""Stored disclosure calendar and unchanged price reactions from a prepared snapshot."""
from contextlib import closing
from pathlib import Path
import sqlite3

import os

DB_PATH = os.environ.get("EXPLORER_PUBLIC_KR_SEASON_DB")
from models.kr_season import KrSeasonOverview
from pipeline.kr_season import read_overview

COLUMNS = {
    'disclosures': {'rcp_no', 'corp_code', 'corp_name', 'report_nm', 'rcept_dt'},
    'companies': {'corp_code', 'corp_name', 'stock_code', 'sector'},
    'public_kr_company_sectors': {'stock_code', 'sector'},
    'stock_prices': {'stock_code', 'trade_date', 'close', 'market_cap'},
    'public_kr_season_coverage': {'season', 'backfilled'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and table in COLUMNS:
        if database == 'main' and column in COLUMNS[table]: return sqlite3.SQLITE_OK
        if database in ('main', None) and column == '': return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'max', 'count', 'like'}: return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    if not (path or DB_PATH):
        raise sqlite3.OperationalError("Public KR season snapshot unavailable")
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    conn.set_authorizer(authorize)
    return conn


def stored_season(season=None, *, path=None, today=None):
    with closing(connection(path)) as conn:
        complete = {r['season'] for r in conn.execute(
            'SELECT season FROM public_kr_season_coverage WHERE backfilled=1')}
        sectors = dict(conn.execute('SELECT stock_code, sector FROM public_kr_company_sectors'))
        return KrSeasonOverview(**read_overview(conn, season, today, is_backfilled=complete.__contains__, sector_of=sectors))

"""Season calculations over an explicitly prepared public US snapshot.

Reaction/expectation/theme text in this snapshot must have public provenance.
The operational database is not a valid snapshot: its follow/core tables and
private-document-derived interpretations must never be copied wholesale.
"""
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3

from models.earnings_season import SeasonOverview
from pipeline import earnings_chain as ec

DB_PATH = os.environ.get("EXPLORER_PUBLIC_US_SEASON_DB")
COLUMNS = {
    "public_us_companies": {"ticker", "company_name", "sector", "market_cap"},
    "earnings_events": {"ticker", "fiscal_year", "fiscal_period", "event_date", "season", "confirmed", "eps_surprise"},
    "transcripts": {"id", "ticker", "fiscal_year", "fiscal_period", "fetched_at"},
    "transcript_reactions": {"transcript_id", "status", "meta_json", "created_at"},
    "earnings_expectations": {"ticker", "fiscal_year", "fiscal_period", "snapshot", "issues_json", "created_at"},
    "season_themes": {"id", "season", "sector", "verdict", "body_json", "created_at"},
    "us_prices": {"stock_code", "trade_date", "close", "volume"},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == "main" and column in COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == "date":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    if not (path or DB_PATH):
        raise sqlite3.OperationalError("Public US season snapshot unavailable")
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    conn.set_authorizer(authorize)
    return conn


def stored_season(season=None, *, path=None, today=None):
    if season is not None and not re.fullmatch(r"[0-9]{4}Q[1-4]", season):
        raise ValueError("Invalid season")
    with closing(connection(path)) as conn:
        fs = {r["ticker"]: dict(r) for r in conn.execute(
            "SELECT ticker, company_name, sector, market_cap FROM public_us_companies")}
        top = {ticker for _, ticker in sorted(
            ((f["market_cap"] or 0, ticker) for ticker, f in fs.items()), reverse=True)[:ec.CORE_TOP_CAP]}
        core = {}
        for ticker, company in fs.items():
            reasons = (["cap"] if ticker in top else []) + (["dc_chain"] if company["sector"] in ec.DC_CHAIN else [])
            if reasons:
                core[ticker] = reasons
        return SeasonOverview(**ec.read_season_overview(
            conn, season, fs=fs, core=core, last_run=None, today=today,
            core_criteria={key: ec.CORE_REASONS[key] for key in ("cap", "dc_chain")},
        ))

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
    "public_us_companies": {"ticker", "company_name", "sector", "market_cap", "fiscal_year_end"},
    "earnings_events": {"ticker", "fiscal_year", "fiscal_period", "event_date", "season", "confirmed", "eps_surprise"},
    "transcripts": {"id", "ticker", "fiscal_year", "fiscal_period", "fetched_at", "call_date", "provider"},
    "transcript_reactions": {"transcript_id", "status", "meta_json", "created_at"},
    "earnings_expectations": {"ticker", "fiscal_year", "fiscal_period", "snapshot", "issues_json", "created_at"},
    "season_themes": {"id", "season", "sector", "verdict", "body_json", "created_at", "tickers"},
    "us_prices": {"stock_code", "trade_date", "close", "volume"},
    "call_momentum": {"ticker", "event_date", "score", "status", "reasons", "first_candidate_at", "summary", "computed_at"},
    "public_us_coverage": {"ticker", "has_release", "extracted_docs", "failed_docs"},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == "main" and column in COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {"date", "datetime", "count", "max"}:
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


def stored_momentum(*, path=None):
    from pipeline import call_momentum as cm
    with closing(connection(path)) as conn:
        names = dict(conn.execute("SELECT ticker, company_name FROM public_us_companies"))
        data = cm.by_season(conn, company_names=names)
        coverage = [dict(r) for r in conn.execute("SELECT ticker, has_release, extracted_docs, failed_docs FROM public_us_coverage") if r['ticker'] in names]
        transcripts = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM transcripts") if r[0] in names}
        comparable = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM call_momentum WHERE status!='first'") if r[0] in names}
        times = [r[1] for r in conn.execute("SELECT ticker, computed_at FROM call_momentum") if r[0] in names and r[1]]
        return {**data, "coverage": {"universe": len(names), "with_releases": sum(bool(r['has_release']) for r in coverage),
            "with_transcripts": len(transcripts), "extracted_docs": sum(r['extracted_docs'] for r in coverage),
            "failed_docs": sum(r['failed_docs'] for r in coverage), "comparable": len(comparable)},
            "as_of": max(times, default=None), "sec_configured": False}


def stored_recent(days=7, limit=40, *, path=None):
    from pipeline.transcript import cy_label
    if not 1 <= days <= 3650 or not 1 <= limit <= 200:
        raise ValueError("Invalid recent call range")
    with closing(connection(path)) as conn:
        rows = conn.execute(
            "SELECT t.id transcript_id,t.ticker,c.company_name,t.fiscal_year,t.fiscal_period,t.call_date,t.provider,t.fetched_at,c.fiscal_year_end "
            "FROM transcripts t JOIN public_us_companies c ON c.ticker=t.ticker WHERE t.fetched_at >= datetime('now',?) "
            "ORDER BY t.fetched_at DESC LIMIT ?", (f'-{days} day', limit)).fetchall()
        return [{**dict(r), "has_digest": False, "cy": cy_label(r['fiscal_year'],r['fiscal_period'],r['fiscal_year_end'])} for r in rows]


def stored_sector(key, season=None, *, path=None, today=None):
    if season is not None and not re.fullmatch(r"[0-9]{4}Q[1-4]", season):
        raise ValueError("Invalid season")
    with closing(connection(path)) as conn:
        fs = {r['ticker']: dict(r) for r in conn.execute('SELECT ticker,company_name,sector,market_cap FROM public_us_companies')}
        if key not in {f['sector'] for f in fs.values()}:
            raise LookupError("Public sector unavailable")
        top = {ticker for _, ticker in sorted(((f['market_cap'] or 0,ticker) for ticker,f in fs.items()), reverse=True)[:ec.CORE_TOP_CAP]}
        core = {ticker: (["cap"] if ticker in top else []) + (["dc_chain"] if f['sector'] in ec.DC_CHAIN else []) for ticker,f in fs.items()}
        return ec.read_sector_detail(conn,key,season,fs=fs,core=core,today=today)

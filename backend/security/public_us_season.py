"""Season calculations over an explicitly prepared public US snapshot.

Reaction/expectation/theme text in this snapshot must have public provenance.
The operational database is not a valid snapshot: its follow/core tables and
private-document-derived interpretations must never be copied wholesale.
"""
from contextlib import closing
from datetime import date
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from models.earnings_season import SeasonOverview
from pipeline import earnings_chain as ec

# Provider pages are not individual article URLs. Existing imports did not retain article URLs.
RESTRICTED_TRANSCRIPT_PROVIDERS = {
    "fool": ("The Motley Fool", "https://www.fool.com/"),
    "alphavantage": ("Alpha Vantage", "https://www.alphavantage.co/"),
}

DB_PATH = os.environ.get("EXPLORER_PUBLIC_US_SEASON_DB")
COLUMNS = {
    "public_regime_recessions": {"snapshot_date", "value"},
    "public_company_evidence": {"ticker", "doc_id", "fingerprint"},
    "public_company_profiles": {"ticker", "payload_json"},
    "public_us_companies": {"ticker", "company_name", "sector", "market_cap", "fiscal_year_end"},
    "earnings_events": {"ticker", "fiscal_year", "fiscal_period", "event_date", "season", "confirmed", "eps_surprise"},
    "transcripts": {"id", "ticker", "fiscal_year", "fiscal_period", "fetched_at", "call_date", "provider"},
    "transcript_reactions": {"transcript_id", "status", "meta_json", "created_at"},
    "earnings_expectations": {"ticker", "fiscal_year", "fiscal_period", "snapshot", "issues_json", "created_at"},
    "season_themes": {"id", "season", "sector", "verdict", "body_json", "created_at", "tickers"},
    "us_prices": {"stock_code", "trade_date", "open", "high", "low", "close", "volume"},
    "call_momentum": {"ticker", "event_date", "score", "status", "reasons", "first_candidate_at", "summary", "computed_at"},
    "public_us_coverage": {"ticker", "has_release", "extracted_docs", "failed_docs"},
    "public_transcript_sources": {"transcript_id", "ticker", "fiscal_year", "fiscal_period", "call_date", "provider", "url"},
    "public_transcript_text": {"transcript_id", "body", "digest"},
    "public_us_calendar": {"ticker", "last_report_date", "next_report_date", "checked_at", "latest_results_date"},
    "us_pt_changes": {"ticker", "graded_at", "firm", "pt_from", "pt_to"},
    "us_fundamentals": {"ticker", "data_json", "fetched_at"},
    "us_quarterly": {"ticker", "metric", "q", "value"},
    "us_segments": {"ticker", "q", "segment_name", "revenue"},
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
        # Existing imports mix restricted transcripts into derived prose. Preserve
        # numerical rankings and metadata while withholding that prose as a unit.
        for rows in [data['candidates'], data['continuing'], *[h['candidates'] for h in data['history']]]:
            for index, row in enumerate(rows):
                if 'transcript' in row.get('sources', []):
                    rows[index] = {**{key: row.get(key) for key in
                        ('ticker','name','event_date','score','first_candidate_at','sources')},
                        'summary':None, 'drivers':[], 'guidance':[], 'qa_focus':[],
                        'beyond_expectation':[], 'tone':None, 'prev_tone':None,
                        'accel':None, 'text_withheld':True}
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
            "SELECT t.id transcript_id,t.ticker,c.company_name,t.fiscal_year,t.fiscal_period,t.call_date,t.provider,t.fetched_at,c.fiscal_year_end,x.digest "
            "FROM transcripts t JOIN public_us_companies c ON c.ticker=t.ticker LEFT JOIN public_transcript_text x ON x.transcript_id=t.id WHERE t.fetched_at >= datetime('now',?) "
            "ORDER BY t.fetched_at DESC LIMIT ?", (f'-{days} day', limit)).fetchall()
        return [{**{k:r[k] for k in r.keys() if k != 'digest'}, "has_digest": bool(r['digest']), "cy": cy_label(r['fiscal_year'],r['fiscal_period'],r['fiscal_year_end'])} for r in rows]


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


def _company(conn, ticker):
    row = conn.execute('SELECT ticker,company_name,sector,market_cap,fiscal_year_end FROM public_us_companies WHERE ticker=?', (ticker.upper(),)).fetchone()
    if row is None:
        raise LookupError('Public company unavailable')
    return dict(row)


def _quarters(conn, company):
    from pipeline.transcript import cy_label
    rows = conn.execute('SELECT t.id,t.fiscal_year,t.fiscal_period,t.call_date,t.provider,x.digest FROM transcripts t '
                        'LEFT JOIN public_transcript_text x ON x.transcript_id=t.id WHERE t.ticker=? '
                        'ORDER BY t.fiscal_year DESC,t.fiscal_period DESC', (company['ticker'],)).fetchall()
    return [{'transcript_id':r['id'],'fiscal_year':r['fiscal_year'],'fiscal_period':r['fiscal_period'],
             'cy':cy_label(r['fiscal_year'],r['fiscal_period'],company['fiscal_year_end']),
             'call_date':r['call_date'],'has_digest':bool(r['digest'])} for r in rows]


def stored_quarters(ticker, *, path=None):
    with closing(connection(path)) as conn:
        return _quarters(conn, _company(conn, ticker))


def stored_companies(*, path=None):
    with closing(connection(path)) as conn:
        companies = [dict(r) for r in conn.execute('SELECT ticker,company_name,sector,market_cap,fiscal_year_end FROM public_us_companies ORDER BY ticker')]
        calendar = {r['ticker']:dict(r) for r in conn.execute('SELECT ticker,last_report_date,next_report_date,checked_at,latest_results_date FROM public_us_calendar')}
        start = ec.season_of(date.today().isoformat())['start']
        out = []
        for f in companies:
            calls = _quarters(conn, f)
            cal = calendar.get(f['ticker'], {})
            latest_results = cal.get('latest_results_date')
            out.append({'ticker':f['ticker'],'company_name':f['company_name'] or f['ticker'],
                        'group_label':None,'category':ec.sector_name(f['sector']),'market_cap':f['market_cap'],
                        'n_calls':len(calls),'latest':calls[0] if calls else None,
                        'last_report_date':cal.get('last_report_date'),'next_report_date':cal.get('next_report_date'),
                        'calendar_checked_at':cal.get('checked_at'),'latest_results_date':latest_results,
                        'season_updated':bool(latest_results and latest_results >= start),
                        'ko_names':[], 'upcoming_expectation':False})
        return out


def _transcript(conn, transcript_id):
    row = conn.execute('SELECT id,ticker,fiscal_year,fiscal_period,call_date,provider FROM transcripts WHERE id=?', (transcript_id,)).fetchone()
    if row is None:
        raise LookupError('Public transcript unavailable')
    return dict(row), _company(conn, row['ticker'])


def _article_url(conn, transcript):
    # Historical snapshots have no link table. Only this missing-table case falls back.
    try:
        row = conn.execute('SELECT ticker,fiscal_year,fiscal_period,call_date,provider,url '
                           'FROM public_transcript_sources WHERE transcript_id=?', (transcript['id'],)).fetchone()
    except sqlite3.OperationalError as exc:
        if str(exc) == 'no such table: public_transcript_sources':
            return None
        raise
    if not row or any(row[k] != transcript[k] for k in ('ticker','fiscal_year','fiscal_period','call_date','provider')):
        return None
    if (row['provider'] != 'fool' or not isinstance(row['url'], str)
            or not isinstance(row['ticker'], str) or not isinstance(row['fiscal_period'], str)):
        return None
    try:
        url = urlsplit(row['url'])
    except ValueError:
        return None
    suffix = f"-{row['ticker'].lower()}-{row['fiscal_period'].lower()}-{row['fiscal_year']}-earnings-call-transcript/"
    if (url.scheme != 'https' or url.netloc != 'www.fool.com' or url.query or url.fragment
            or not re.fullmatch(r'/earnings/call-transcripts/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/', url.path)
            or not url.path.endswith(suffix)):
        return None
    return row['url']


def stored_detail(transcript_id, *, path=None):
    from pipeline.transcript import cy_label
    with closing(connection(path)) as conn:
        t, f = _transcript(conn, transcript_id)
        text = conn.execute('SELECT body,digest FROM public_transcript_text WHERE transcript_id=?', (transcript_id,)).fetchone()
        source = RESTRICTED_TRANSCRIPT_PROVIDERS.get(t['provider'])
        published = text is not None
        article = _article_url(conn, t) if source else None
        return {'transcript_id':t['id'],'ticker':t['ticker'],'company_name':f['company_name'] or t['ticker'],
                'fiscal_year':t['fiscal_year'],'fiscal_period':t['fiscal_period'], 'call_date':t['call_date'],
                'cy':cy_label(t['fiscal_year'],t['fiscal_period'],f['fiscal_year_end']),
                'body':text['body'] if published else '', 'digest':text['digest'] if published else None,
                'content_status':'published' if published else 'source_only',
                'source_name':source[0] if source else None, 'source_url':article or (source[1] if source else None),
                'source_link_kind':'article' if article else ('provider' if source else None),
                'nodes':[],'causal_edges':[],'proxies':[]}


def stored_chain(transcript_id, *, path=None, today=None):
    with closing(connection(path)) as conn:
        t, f = _transcript(conn, transcript_id)
        return ec.read_chain_detail(conn,t=t,f=f,expectation=None,today=today)


def stored_upcoming(ticker, *, path=None, today=None):
    with closing(connection(path)) as conn:
        f = _company(conn, ticker)
        today_s = today or date.today().isoformat()
        ev = ec.next_event(conn,f['ticker'],today_s)
        if ev is None:
            raise LookupError('Upcoming public event unavailable')
        return ec.read_upcoming_detail(conn,f['ticker'],f=f,ev=ev,exp=None,today_s=today_s)

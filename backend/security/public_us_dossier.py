"""Stored company metrics and financials from the prepared US company snapshot."""
from contextlib import closing
import json

from models.us import UsDossier
from pipeline import earnings_chain as ec
from pipeline import income_flow
from security.public_us_season import connection, _company


def stored_dossier(ticker, *, path=None):
    with closing(connection(path)) as conn:
        company = _company(conn, ticker)
        ticker = company['ticker']
        row = conn.execute('SELECT data_json,fetched_at FROM us_fundamentals WHERE ticker=?', (ticker,)).fetchone()
        latest = conn.execute('SELECT id,fiscal_year,fiscal_period,call_date FROM transcripts WHERE ticker=? ORDER BY call_date DESC LIMIT 1', (ticker,)).fetchone()
        return UsDossier(ticker=ticker,name=company['company_name'] or ticker,entity_id=None,
                         fundamentals=json.loads(row['data_json']) if row else None,
                         fundamentals_fetched_at=row['fetched_at'] if row else None,
                         latest_transcript=dict(latest) if latest else None,
                         sector=ec.sector_name(company['sector']),sector_etf=ec.sector_etf(company['sector']))


def stored_prices(ticker, *, path=None):
    with closing(connection(path)) as conn:
        company = _company(conn, ticker)
        rows=conn.execute('SELECT trade_date,open,high,low,close,volume,NULL AS market_cap FROM us_prices '
                          'WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1500',(company['ticker'],)).fetchall()
        return {'items':[dict(r) for r in reversed(rows)]}


def stored_income(ticker, quarter=None, mode='q', *, path=None):
    with closing(connection(path)) as conn:
        company = _company(conn,ticker)
        result = income_flow.us_income_flow(company['ticker'],quarter,mode,conn=conn)
        if result is None:
            raise LookupError('Public income data unavailable')
        return result


def stored_income_quarters(ticker, *, path=None):
    with closing(connection(path)) as conn:
        company = _company(conn,ticker)
        return income_flow.us_income_flow_quarters(company['ticker'],conn=conn)

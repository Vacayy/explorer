"""Fixture-only reader for the existing US sector map."""
import re

from pipeline.us_sectors import SPY, TICKERS, etf_of, us_map_from_data


def us_map(connection):
    database, schema = connection.execute('SELECT current_database(), current_schema()').fetchone()
    if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
        raise ValueError('Only a disposable fixture is supported')
    if (connection.execute('SHOW transaction_isolation').fetchone()[0] not in ('repeatable read', 'serializable')
            or connection.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A read-only repeatable-read transaction is required')
    metadata = connection.execute(
        'SELECT u.generation_id,m.generation_id,m.linked_document_generation,s.generation_id,u.classifications '
        'FROM sector_market_us_metadata u CROSS JOIN sector_market_metadata m CROSS JOIN snapshot_metadata s '
        'WHERE u.singleton AND m.singleton AND s.singleton').fetchone()
    if metadata is None or not metadata[2] or metadata[0] != metadata[1] or metadata[0] != metadata[3]:
        raise ValueError('US sector data does not match the current generation')
    classifications = connection.execute('SELECT ticker,sector,industry FROM sector_market_us_classifications').fetchall()
    if len(classifications) != metadata[4]:
        raise ValueError('Incomplete US sector classifications')
    sectors = {ticker: (sector, industry) for ticker, sector, industry in classifications}
    followed = []
    for row, in connection.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='transcript_follow' ORDER BY row_ordinal"):
        if row['active'] != 1:
            continue
        sector, industry = sectors.get(row['ticker'], (None, None))
        gics, sub = etf_of(sector, industry)
        followed.append({'ticker': row['ticker'], 'name': row['company_name'], 'entity_id': row['entity_id'],
                         'market_cap': row['market_cap'], 'sector': sector, 'industry': industry,
                         'gics': gics, 'sub': sub})
    series = {ticker: [] for ticker in [*TICKERS, SPY]}
    for ticker, day, close in connection.execute(
            'SELECT ticker,trade_date,close FROM sector_market_benchmark_prices WHERE ticker=ANY(%s) '
            'ORDER BY trade_date COLLATE "C"', ([*TICKERS, SPY],)):
        series[ticker].append((day, close))
    return us_map_from_data(series, followed)

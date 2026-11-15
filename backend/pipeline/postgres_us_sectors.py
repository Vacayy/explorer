"""Fixture-only data source for the existing US sector map and details."""
import re
from datetime import date, timedelta

from pipeline.us_sectors import (SPY, TICKERS, DOC_DAYS, DOC_LIMIT, DOC_TYPES,
                                 etf_of, us_map_from_data, us_sector_detail_from_source)


class PostgreSQLUsSource:
    def __init__(self, connection):
        self.connection = connection
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
        self.classifications = {ticker: (sector, industry) for ticker, sector, industry in classifications}

    def follows(self):
        followed = []
        for row, in self.connection.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='transcript_follow' ORDER BY row_ordinal"):
            if row['active'] != 1:
                continue
            sector, industry = self.classifications.get(row['ticker'], (None, None))
            gics, sub = etf_of(sector, industry)
            followed.append({'ticker': row['ticker'], 'name': row['company_name'], 'entity_id': row['entity_id'],
                             'market_cap': row['market_cap'], 'sector': sector, 'industry': industry,
                             'gics': gics, 'sub': sub})
        return followed

    def series(self):
        series = {ticker: [] for ticker in [*TICKERS, SPY]}
        for ticker, day, close in self.connection.execute(
                'SELECT ticker,trade_date,close FROM sector_market_benchmark_prices WHERE ticker=ANY(%s) '
                'ORDER BY trade_date COLLATE "C"', ([*TICKERS, SPY],)):
            series[ticker].append((day, close))
        return series

    def member_prices(self, ticker, since):
        return self.connection.execute('SELECT trade_date,close FROM sector_market_us_prices '
                                       'WHERE stock_code=%s AND trade_date>=%s ORDER BY trade_date COLLATE "C"',
                                       (ticker, since)).fetchall()

    def documents(self, members, as_of):
        ids = [member['entity_id'] for member in members if member['entity_id']]
        if not ids:
            return []
        since = (date.fromisoformat(as_of) - timedelta(days=DOC_DAYS)).isoformat()
        rows = self.connection.execute(
            'SELECT d.id,d.source_type,d.title,d.published_at,count(DISTINCT l.entity_id) AS hits '
            'FROM sector_market_document_links l JOIN sector_market_documents d ON d.id=l.doc_id '
            'WHERE l.entity_id=ANY(%s) AND d.published_at >= %s AND d.source_type=ANY(%s) '
            'GROUP BY d.id,d.source_type,d.title,d.published_at '
            'ORDER BY hits DESC,d.published_at COLLATE "C" DESC,d.id LIMIT %s',
            (ids, since, list(DOC_TYPES), DOC_LIMIT),
        ).fetchall()
        return [{'id': ident, 'type': source_type, 'title': (title or '').strip() or '(제목 없음)',
                 'published_at': published_at, 'hits': hits} for ident, source_type, title, published_at, hits in rows]

    def season_themes(self, keys):
        season = self.connection.execute('SELECT max(season) FROM sector_market_season_themes WHERE sector=ANY(%s)',
                                         (list(keys),)).fetchone()[0]
        rows = self.connection.execute('SELECT sector,verdict,body_json FROM sector_market_season_themes '
                                       'WHERE season=%s AND sector=ANY(%s) ORDER BY id',
                                       (season, list(keys))).fetchall() if season else []
        return season, {sector: {'sector': sector, 'verdict': verdict, 'body_json': body} for sector, verdict, body in rows}

    def taiwan_revenue(self, codes):
        ym = self.connection.execute('SELECT max(ym) FROM sector_market_taiwan_revenue').fetchone()[0]
        values = [row[0] for row in self.connection.execute(
            'SELECT yoy_pct FROM sector_market_taiwan_revenue WHERE ym=%s AND yoy_pct IS NOT NULL AND code=ANY(%s)',
            (ym, codes))] if ym and codes else []
        return ym, values

    def kr_sector_map(self):
        from pipeline.postgres_sector_market import PostgreSQLSectorSource
        from pipeline.sector_rs import build_sector_map
        return build_sector_map(PostgreSQLSectorSource(self.connection))


def us_map(connection):
    source = PostgreSQLUsSource(connection)
    return us_map_from_data(source.series(), source.follows())


def us_sector_detail(connection, ticker):
    return us_sector_detail_from_source(PostgreSQLUsSource(connection), ticker)

"""Experimental sector map snapshot and reader; never registered in live API.

The caller supplies a query-only SQLite read transaction and an isolated
PostgreSQL connection. COPY streams rows without retaining the price history in
memory. PostgreSQL replacement is one transaction, so a failure rolls back.
This captures a derived membership map, not all source tables or Peer files.
"""
from pipeline.sector_overrides import effective_sectors

_LOCK_KEY = 0x534543544F524D50
_COLUMNS = ('id', 'stock_code', 'trade_date', 'open', 'high', 'low', 'close',
            'volume', 'market_cap', 'shares', 'fetched_at')


def load_sector_market(source, destination):
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('A query-only SQLite transaction is required')
    # Mapping is small; the 1M+ price history below is never materialized.
    members = effective_sectors(source)
    count = 0
    with destination.transaction():
        destination.execute('SELECT pg_advisory_xact_lock(%s)', (_LOCK_KEY,))
        destination.execute('TRUNCATE sector_market_prices, sector_market_membership, '
                            'sector_market_groups, sector_market_peer_links, '
                            'sector_market_benchmarks, sector_market_benchmark_prices, sector_market_index')
        with destination.cursor().copy(
            'COPY sector_market_prices (' + ', '.join(_COLUMNS) + ') FROM STDIN'
        ) as copy:
            for row in source.execute('SELECT ' + ', '.join(_COLUMNS) + ' FROM stock_prices'):
                copy.write_row(tuple(row))
                count += 1
        with destination.cursor().copy(
            'COPY sector_market_membership (stock_code, sector) FROM STDIN'
        ) as copy:
            for row in members.items():
                copy.write_row(row)
        with destination.cursor().copy('COPY sector_market_groups (sector) FROM STDIN') as copy:
            for row in source.execute('SELECT DISTINCT group_name FROM sector_map'):
                copy.write_row(tuple(row))
        with destination.cursor().copy('''COPY sector_market_peer_links
            (sector, peer_group_id, sort, partial, note, source) FROM STDIN''') as copy:
            for row in source.execute('''SELECT sector, peer_group_id, sort, partial, note, source
                                          FROM sector_peer_map'''):
                copy.write_row(tuple(row))
        for target, columns, table in (
            ('sector_market_benchmarks', 'sector, ticker, name, tracks, note', 'sector_benchmarks'),
            ('sector_market_benchmark_prices', 'ticker, trade_date, close', 'sector_benchmark_prices'),
            ('sector_market_index', 'sector, trade_date, value', 'sector_index'),
        ):
            with destination.cursor().copy(f'COPY {target} ({columns}) FROM STDIN') as copy:
                for row in source.execute(f'SELECT {columns} FROM {table}'):
                    copy.write_row(tuple(row))
    return {'prices': count, 'members': len(members)}


class PostgreSQLSectorSource:
    """Use one caller-owned REPEATABLE READ transaction for every map lookup."""

    def __init__(self, conn):
        self.conn = conn

    def latest_date(self):
        return self.conn.execute('SELECT max(trade_date) FROM sector_market_prices').fetchone()[0]

    def members(self):
        return dict(self.conn.execute('SELECT stock_code, sector FROM sector_market_membership'))

    def benchmarks(self):
        return {sector: {'ticker': ticker, 'name': name, 'tracks': tracks, 'note': note,
                         'kind': 'etf' if ticker else 'computed'}
                for sector, ticker, name, tracks, note in self.conn.execute(
                    'SELECT sector, ticker, name, tracks, note FROM sector_market_benchmarks')}

    def benchmark_series(self, sector, bench):
        if bench and bench.get('ticker'):
            return list(self.conn.execute('SELECT trade_date, close FROM sector_market_benchmark_prices '
                                          'WHERE ticker = %s ORDER BY trade_date', (bench['ticker'],)))
        return list(self.conn.execute('SELECT trade_date, value FROM sector_market_index '
                                      'WHERE sector = %s ORDER BY trade_date', (sector,)))

    def kospi_series(self):
        from pipeline.sector_benchmarks import KOSPI
        return list(self.conn.execute('SELECT trade_date, close FROM sector_market_benchmark_prices '
                                      'WHERE ticker = %s ORDER BY trade_date', (KOSPI,)))

    def sector_peers(self, runtime):
        """Combine same-transaction DB rows with the caller's validated Peer bundle."""
        from pipeline.sector_peers import AUTO_SHARE, build
        sectors = sorted(row[0] for row in self.conn.execute('SELECT sector FROM sector_market_groups'))
        rows = [dict(zip(('sector', 'peer_group_id', 'sort', 'partial', 'note', 'source'), row))
                for row in self.conn.execute('SELECT sector, peer_group_id, sort, partial, note, source '
                                             'FROM sector_market_peer_links')]
        groups = [{'id': g.id, 'name': g.name, 'scope': g.scope} for g in runtime.catalog.groups]
        members = {}
        for company in runtime.catalog.companies:
            for group in company.groupIds:
                members.setdefault(group, []).append(company.code)
        return {'catalog_as_of': str(runtime.catalog.asOf), 'auto_share': AUTO_SHARE,
                'sectors': build(sectors, rows, groups, members, self.members())}

    def snapshot(self, as_of):
        rows = self.conn.execute('''
            WITH RECURSIVE codes(stock_code) AS (
                (SELECT stock_code FROM sector_market_prices
                 WHERE close IS NOT NULL
                 ORDER BY stock_code COLLATE "C" LIMIT 1)
                UNION ALL
                SELECT next_code.stock_code FROM codes
                CROSS JOIN LATERAL (
                    SELECT stock_code FROM sector_market_prices
                    WHERE close IS NOT NULL
                      AND stock_code COLLATE "C" > codes.stock_code COLLATE "C"
                    ORDER BY stock_code COLLATE "C" LIMIT 1
                ) next_code
            )
            SELECT codes.stock_code, price.close, price.market_cap
            FROM codes CROSS JOIN LATERAL (
                SELECT close, market_cap FROM sector_market_prices
                WHERE stock_code COLLATE "C" = codes.stock_code COLLATE "C"
                  AND trade_date <= %s AND close IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            ) price
        ''', (as_of,))
        return {code: (close, market_cap or 0) for code, close, market_cap in rows}

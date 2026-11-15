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
        destination.execute('TRUNCATE sector_market_prices, sector_market_membership')
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
    return {'prices': count, 'members': len(members)}


class PostgreSQLSectorSource:
    """Use one caller-owned REPEATABLE READ transaction for every map lookup."""

    def __init__(self, conn):
        self.conn = conn

    def latest_date(self):
        return self.conn.execute('SELECT max(trade_date) FROM sector_market_prices').fetchone()[0]

    def members(self):
        return dict(self.conn.execute('SELECT stock_code, sector FROM sector_market_membership'))

    def snapshot(self, as_of):
        rows = self.conn.execute('''
            SELECT DISTINCT ON (stock_code COLLATE "C") stock_code, close, market_cap
            FROM sector_market_prices
            WHERE trade_date <= %s AND close IS NOT NULL
            ORDER BY stock_code COLLATE "C", trade_date DESC
        ''', (as_of,))
        return {code: (close, market_cap or 0) for code, close, market_cap in rows}

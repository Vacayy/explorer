"""Preserve legacy portfolio principles in an empty disposable PG snapshot."""
import os
import re

from psycopg.types.json import Jsonb


TABLES = ('portfolio_principles', 'portfolio_principle_state', 'portfolio_alerts_sent')


class PortfolioArchiveConflict(RuntimeError):
    pass


def import_principle_archive(source, target):
    """Copy complete original rows into empty snapshot tables in one transaction.

    The source must be a consistent SQLite backup; caller owns both connections.
    Captured tables retain their original schemas and row order for legacy reads.
    This is a fixture-only import, not a live-data synchronizer.
    """
    database, schema = target.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or not schema or
            not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    source.execute('PRAGMA query_only=ON')
    if not source.in_transaction:
        source.execute('BEGIN')
    counts = {}
    with target.transaction():
        target.execute('LOCK TABLE legacy_snapshot_tables,legacy_snapshot_rows IN EXCLUSIVE MODE')
        if target.execute('SELECT EXISTS(SELECT 1 FROM legacy_snapshot_tables WHERE table_name=ANY(%s))',
                          (list(TABLES),)).fetchone()[0]:
            raise PortfolioArchiveConflict('target already contains portfolio principle data')
        for table in TABLES:
            meta = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not meta or not meta[0]:
                raise PortfolioArchiveConflict(f'source table missing: {table}')
            columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            if not columns:
                raise PortfolioArchiveConflict(f'source table has no columns: {table}')
            cursor = source.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            rows = [dict(zip(columns, row)) for row in cursor]
            target.execute('INSERT INTO legacy_snapshot_tables(table_name,columns,schema_sql,row_count) VALUES (%s,%s,%s,%s)',
                           (table, Jsonb(columns), meta[0], len(rows)))
            with target.cursor() as out:
                out.executemany('INSERT INTO legacy_snapshot_rows(table_name,row_ordinal,row_data) VALUES (%s,%s,%s)',
                                [(table, i, Jsonb(row)) for i, row in enumerate(rows)])
            counts[table] = len(rows)
    return counts

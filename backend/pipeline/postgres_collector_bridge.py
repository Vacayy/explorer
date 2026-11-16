"""Interim collector bridge for the single-path preview (compatibility path, not the target design).

Unchanged legacy collectors keep writing their own SQLite file (single writer).
Before a run, the owner's PG ledgers are exported into that file's legacy tables
so collectors read current pins, groups and rules; after a run, the collected
tables are copied back into the candidate's supplement layer in one transaction.
Base snapshot tables are never replaced here.
"""
import json
import sqlite3

from pipeline.postgres_graph_fixture import _guard


def export_owner_records(pg, collector):
    """Write the owner's current ledgers into the collector's legacy tables."""
    from pipeline import postgres_owner_legacy_fixture as owner_legacy
    from pipeline.postgres_legacy_projection import _derive_owner_legacy, _derive_owner_portfolio, _derive_owner_records
    _guard(pg)
    if pg.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is not None:
        _derive_owner_legacy(collector, pg, owner_legacy.load(pg)[1])
    _derive_owner_portfolio(collector, pg)
    _derive_owner_records(collector, pg)
    collector.commit()


def refresh_supplement(pg, collector_path, tables):
    """Replace the named supplement tables with the collector's rows, atomically."""
    _guard(pg)
    source = sqlite3.connect(f'file:{collector_path}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute('BEGIN')  # one consistent read of the collector file
        counts = {}
        with pg.transaction():
            pg.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')
            known = {name: columns for name, columns in pg.execute(
                'SELECT table_name,columns FROM legacy_supplement_tables WHERE table_name=ANY(%s)', (list(tables),))}
            if set(known) != set(tables):
                raise ValueError('Only existing supplement tables can be refreshed')
            for name in tables:
                columns = [row['name'] for row in source.execute(f'PRAGMA table_info("{name}")')]
                if columns != known[name]:
                    raise ValueError(f'Collector schema differs: {name}')
                pg.execute('DELETE FROM legacy_supplement_rows WHERE table_name=%s', (name,))
                count = 0
                with pg.cursor().copy('COPY legacy_supplement_rows (table_name,row_ordinal,row_data) FROM STDIN') as copy:
                    for ordinal, row in enumerate(source.execute(f'SELECT * FROM "{name}"')):
                        copy.write_row((name, ordinal, json.dumps(dict(row), ensure_ascii=False, allow_nan=False)))
                        count = ordinal + 1
                pg.execute('UPDATE legacy_supplement_tables SET row_count=%s WHERE table_name=%s', (count, name))
                counts[name] = count
        return counts
    finally:
        source.close()

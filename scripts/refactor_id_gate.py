"""Candidate rows in the MacBook's legacy id range (architect #3 6945367459 items 1 and 4).

For every legacy table with an integer primary key in the 11-14 base (/base/stock_explorer.db), counts the rows the
candidate shows with base max < id < the candidate band (refactor_collect_trial.ID_BANDS; 100 million, evidence
10 billion): the snapshot view (overrides and overlays included), the supplement rows and the group ledger. Such a
row would meet the MacBook's next ids at the cutover. Prints one line per table with rows, and where they live.
As the T0 gate (--gate) it exits 1 unless the count is 0.

  python /app/scripts/refactor_id_gate.py [--gate]
"""
import json
import os
import sqlite3
import sys

import psycopg

BASE = '/base/stock_explorer.db'
BAND, EVIDENCE_BAND = 100_000_000, 10_000_000_000


def integer_keyed(base):
    out = {}
    for (table,) in base.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                 "AND sql NOT LIKE 'CREATE VIRTUAL%'").fetchall():
        try:
            info = base.execute(f'PRAGMA table_info("{table}")').fetchall()
        except sqlite3.OperationalError:  # a vector index's shadow table (its module is not loaded here)
            continue
        keys = [row for row in info if row[5]]
        if len(keys) == 1 and keys[0][2].upper() == 'INTEGER':
            column = keys[0][1]
            out[table] = (column, base.execute(f'SELECT COALESCE(max("{column}"),0) FROM "{table}"').fetchone()[0])
    return out


def scan(pg, tables):
    found = {}
    for table, (column, top) in sorted(tables.items()):
        band = EVIDENCE_BAND if table == 'narrative_edge_evidence' else BAND
        where = {}
        for label, sql, params in (
                ('snapshot', "SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s AND (row_data->>%s) ~ '^-?[0-9]+$' "
                             "AND (row_data->>%s)::numeric > %s AND (row_data->>%s)::numeric < %s",
                 (table, column, column, top, column, band)),
                ('supplement', "SELECT count(*) FROM legacy_supplement_rows WHERE table_name=%s AND (row_data->>%s) ~ '^-?[0-9]+$' "
                               "AND (row_data->>%s)::numeric > %s AND (row_data->>%s)::numeric < %s",
                 (table, column, column, top, column, band)),
                ('group_ledger', 'SELECT count(*) FROM owner_legacy_rows WHERE table_name=%s AND pk > %s AND pk < %s',
                 (table, top, band))):
            n = pg.execute(sql, params).fetchone()[0]
            if n:
                where[label] = n
        if where:
            overridden = pg.execute("SELECT count(*) FROM owner_row_overrides WHERE table_name=%s AND key ~ '^[0-9]+$' "
                                    'AND key::numeric > %s AND key::numeric < %s', (table, top, band)).fetchone()[0]
            if overridden:
                where['of_which_overrides'] = overridden
            found[table] = {'key': column, 'base_max': top, **where}
    return found


def main():
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    base = sqlite3.connect(f'file:{BASE}?mode=ro&immutable=1', uri=True)
    tables = integer_keyed(base)
    with psycopg.connect(dsn, options=f'-c search_path={schema}') as pg:
        found = scan(pg, tables)
    print(json.dumps({'integer_keyed_tables': len(tables), 'tables_with_rows': len(found), 'found': found}, ensure_ascii=False))
    if '--gate' in sys.argv[1:] and found:
        sys.exit(1)


if __name__ == '__main__':
    main()

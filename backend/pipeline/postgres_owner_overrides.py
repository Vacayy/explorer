"""Operator decisions and on-demand computations over collected rows, by key (single-path candidate).

Admin flags, regime checklist entries, research-candidate and agent-proposal dismissals, and alias
rejections change a few rows of tables the collector also writes; screen computations (investor
lens, source profile, upside model, MER narrative) write one result row each. The unchanged legacy handler runs
on writable TEMP copies of these tables (`routers.postgres_owner_overrides_fixture`); the rows it
changed are kept here and laid over the collected rows in every read path and in the collector export.
A removed row is kept as a NULL override.
"""
import re

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

# table -> natural key column
OVERRIDES = {'feature_flags': 'name', 'era_checks': 'key', 'research_candidates': 'id',
             'agent_proposals': 'id', 'entity_keywords': 'id',
             'lens_readings': 'id', 'source_digests': 'id', 'models': 'id', 'narratives': 'id'}
# Computation outputs: copied into TEMP only for the computing request; reads see them from the
# next projection build (the computing request answers with the result itself).
COMPUTED = ('lens_readings', 'source_digests', 'models', 'narratives')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('owner_row_overrides')").fetchone()[0] is not None:
            raise ValueError('Row overrides already initialized')
        conn.execute('CREATE TABLE owner_row_overrides (table_name TEXT NOT NULL,key TEXT NOT NULL,row_data JSONB,'
                     'updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(table_name,key))')


def writable_ddl(ddl):
    """The table's own DDL without foreign keys: its parents are not copied into TEMP."""
    return re.sub(r'\s+REFERENCES\s+\w+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*',
                  '', ddl, flags=re.I)


def rows(conn):
    """{table: {key: row}} of a SQLite connection's (TEMP) override tables."""
    out = {}
    temp = {row[0] for row in conn.execute("SELECT name FROM temp.sqlite_master WHERE type='table'")}
    for table, key in OVERRIDES.items():
        if table in temp:
            out[table] = {str(row[key]): dict(row) for row in conn.execute(f'SELECT * FROM temp."{table}"')}
    return out


def apply(conn, before, after):
    """Store what one successful request changed; returns the number of changed rows."""
    changed = 0
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-row-overrides',0))")
    for table in after:
        old, new = before[table], after[table]
        for key in set(old) | set(new):
            if old.get(key) != new.get(key):
                row = new.get(key)
                conn.execute('INSERT INTO owner_row_overrides(table_name,key,row_data) VALUES (%s,%s,%s) '
                             'ON CONFLICT (table_name,key) DO UPDATE SET row_data=excluded.row_data,updated_at=now()',
                             (table, key, Jsonb(row) if row is not None else None))
                changed += 1
    return changed


def derive(root, pg, *, skip=()):
    """Lay the kept decisions over the collected rows (a NULL override removes the row)."""
    if pg.execute("SELECT to_regclass('owner_row_overrides')").fetchone()[0] is None:
        return
    for table, key, row in pg.execute('SELECT table_name,key,row_data FROM owner_row_overrides ORDER BY updated_at'):
        if table in skip:
            continue
        column = OVERRIDES[table]
        if row is None:
            root.execute(f'DELETE FROM "{table}" WHERE "{column}"=?', (key,))
            continue
        columns = [c[1] for c in root.execute(f'PRAGMA table_info("{table}")') if c[1] in row]
        if root.execute(f'UPDATE "{table}" SET {",".join(f"{c}=?" for c in columns)} WHERE "{column}"=?',
                        [row[c] for c in columns] + [key]).rowcount == 0:
            root.execute(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                         [row[c] for c in columns])

"""Same-generation legacy tables added beside a disposable single-path snapshot.

The base snapshot holds only the tables with explicit document contracts. Home,
macro and search still read many collected tables through legacy SQL; this adds
those rows from the very backup the base was loaded from, without touching the
base schema or the PG-native ledgers that replaced legacy user tables.
"""
import json
import sqlite3
from pathlib import Path

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_snapshot import _insert_batches

# Collected/reference data read by existing home, macro, search and home tabs.
# Excluded: tables replaced by PG-native ledgers, chunk/financial bulk loaded by
# later units, and telemetry that the read paths do not need.
EXCLUDED = frozenset({'doc_chunks', 'llm_calls', 'usage_events',
                      'api_requests_hourly', 'client_errors', 'image_backfill_docs'})
# Not telemetry after all: the contradiction scan's record of judged documents (without it the neutral pairs of
# the last 7 days are judged again every day). Registered empty until the next import carries the collector's rows.
DOC_SCANS_DDL = ('CREATE TABLE knowledge_doc_scans (\n        doc_id     INTEGER PRIMARY KEY REFERENCES raw_documents(id) '
                 "ON DELETE CASCADE,\n        scanned_at TEXT DEFAULT (datetime('now'))\n    )")


def has_doc_scans(conn):
    return conn.execute("SELECT 1 FROM legacy_supplement_tables WHERE table_name='knowledge_doc_scans'").fetchone() is not None


def initialize_doc_scans(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute("INSERT INTO legacy_supplement_tables (table_name,columns,schema_sql,row_count) VALUES "
                     "('knowledge_doc_scans',%s,%s,0) ON CONFLICT DO NOTHING", (Jsonb(['doc_id', 'scanned_at']), DOC_SCANS_DDL))


def initialize_supplement(target):
    _guard(target)
    if target.execute("SELECT to_regclass('legacy_supplement_rows')").fetchone()[0] is not None:
        raise ValueError('Legacy supplement already initialized')
    with target.transaction():
        target.execute('CREATE TABLE legacy_supplement_tables (table_name TEXT PRIMARY KEY,columns JSONB NOT NULL,'
                       'schema_sql TEXT NOT NULL,row_count BIGINT NOT NULL)')
        target.execute('CREATE TABLE legacy_supplement_rows (table_name TEXT NOT NULL REFERENCES legacy_supplement_tables,'
                       'row_ordinal BIGINT NOT NULL,row_data JSONB NOT NULL,PRIMARY KEY(table_name,row_ordinal))')
        for view, columns in (('legacy_snapshot_tables', 'table_name,columns,schema_sql,row_count'),
                              ('legacy_snapshot_rows', 'table_name,row_ordinal,row_data')):
            definition = target.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', (view,)).fetchone()[0]
            if definition is None or 'legacy_supplement' in definition:
                raise ValueError('Unexpected snapshot view')
            supplement = view.replace('legacy_snapshot', 'legacy_supplement')
            target.execute(f'CREATE OR REPLACE VIEW {view} AS {definition.rstrip().rstrip(";")} '
                           f'UNION ALL SELECT {columns} FROM {supplement}')


def load_supplement(target, backup_dir, *, only=None):
    """Copy missing collected tables from the base snapshot's own backup in one transaction.

    `only` adds the named tables to an already loaded supplement.
    """
    _guard(target)
    backup = Path(backup_dir)
    manifest = json.loads((backup / 'manifest.json').read_text())
    path = backup / manifest['file']
    if path.stat().st_size != manifest['size_bytes'] or any(backup.glob(manifest['file'] + '-*')):
        raise ValueError('Backup file does not match its manifest')
    source = sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)
    source.row_factory = sqlite3.Row
    try:
        with target.transaction():
            target.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')
            if only is None and target.execute('SELECT 1 FROM legacy_supplement_tables LIMIT 1').fetchone():
                raise ValueError('Legacy supplement already loaded')
            documents = target.execute('SELECT document_count FROM snapshot_metadata WHERE singleton').fetchone()[0]
            if source.execute('SELECT count(*) FROM raw_documents').fetchone()[0] != documents:
                raise ValueError('Backup is not the base snapshot generation')
            present = dict(target.execute('SELECT table_name,row_count FROM legacy_snapshot_tables').fetchall())
            # Every base table must hold the backup's exact row count before rows are mixed.
            for name, count in present.items():
                if source.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] != count:
                    raise ValueError(f'Backup differs from base snapshot: {name}')
            native = {row[0] for row in target.execute("SELECT table_name FROM information_schema.tables "
                                                       "WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}
            schemas = source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            virtual = [name for name, ddl in schemas if 'VIRTUAL TABLE' in (ddl or '').upper()]
            if only is not None and (set(only) - {name for name, _ in schemas} or set(only) & set(present)):
                raise ValueError('Requested tables are missing from the backup or already present')
            loaded = {}
            for name, ddl in schemas:
                if only is not None and name not in only:
                    continue
                if (name in present or name in native or name in EXCLUDED or name in virtual
                        or any(name.startswith(v + '_') for v in virtual) or not ddl):
                    continue
                columns = [r['name'] for r in source.execute(f'PRAGMA table_info("{name}")')]
                count = source.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                target.execute('INSERT INTO legacy_supplement_tables VALUES (%s,%s::jsonb,%s,%s)',
                               (name, json.dumps(columns), ddl, count))
                # One COPY statement: fast, and statement triggers (projection version) fire once.
                with target.cursor().copy('COPY legacy_supplement_rows (table_name,row_ordinal,row_data) FROM STDIN') as copy:
                    for ordinal, row in enumerate(source.execute(f'SELECT * FROM "{name}"')):
                        copy.write_row((name, ordinal, json.dumps(dict(row), ensure_ascii=False, allow_nan=False)))
                loaded[name] = count
            return loaded
    finally:
        source.close()


def load_indexes(target, backup_dir):
    """Keep the backup's own index DDL so projections answer legacy joins at legacy speed."""
    _guard(target)
    backup = Path(backup_dir)
    manifest = json.loads((backup / 'manifest.json').read_text())
    path = backup / manifest['file']
    if path.stat().st_size != manifest['size_bytes']:
        raise ValueError('Backup file does not match its manifest')
    source = sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)
    try:
        with target.transaction():
            if target.execute("SELECT to_regclass('legacy_snapshot_indexes')").fetchone()[0] is not None:
                raise ValueError('Legacy indexes already loaded')
            documents = target.execute('SELECT document_count FROM snapshot_metadata WHERE singleton').fetchone()[0]
            if source.execute('SELECT count(*) FROM raw_documents').fetchone()[0] != documents:
                raise ValueError('Backup is not the base snapshot generation')
            tables = {row[0] for row in target.execute('SELECT table_name FROM legacy_snapshot_tables')}
            target.execute('CREATE TABLE legacy_snapshot_indexes (name TEXT PRIMARY KEY,table_name TEXT NOT NULL,sql TEXT NOT NULL)')
            rows = [r for r in source.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
                    if r[1] in tables]
            _insert_batches(target, 'INSERT INTO legacy_snapshot_indexes VALUES (%s,%s,%s)', rows)
            return len(rows)
    finally:
        source.close()


def adopt_base_tables(target, tables):
    """Move base tables the collector owns into the supplement, so `refresh_supplement` can replace them.

    Their base rows are copied unchanged and then hidden; the base schema is not touched.
    Only tables no overlay writes to can be adopted.
    """
    _guard(target)
    with target.transaction():
        target.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')
        if target.execute("SELECT to_regclass('legacy_adopted_tables')").fetchone()[0] is None:
            target.execute('CREATE TABLE legacy_adopted_tables (table_name TEXT PRIMARY KEY)')
            for view, columns in (('legacy_snapshot_tables', 'table_name,columns,schema_sql,row_count'),
                                  ('legacy_snapshot_rows', 'table_name,row_ordinal,row_data')):
                definition = target.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', (view,)).fetchone()[0]
                supplement = view.replace('legacy_snapshot', 'legacy_supplement')
                target.execute(f'''CREATE OR REPLACE VIEW {view} AS
                    SELECT {columns} FROM ({definition.rstrip().rstrip(";")}) v
                    WHERE v.table_name NOT IN (SELECT table_name FROM legacy_adopted_tables)
                    UNION ALL SELECT {columns} FROM {supplement} s
                    WHERE s.table_name IN (SELECT table_name FROM legacy_adopted_tables)''')
        counts = {}
        for name in tables:
            row = target.execute('SELECT columns,schema_sql,row_count FROM legacy_snapshot_tables WHERE table_name=%s', (name,)).fetchone()
            if row is None or target.execute('SELECT 1 FROM legacy_supplement_tables WHERE table_name=%s', (name,)).fetchone():
                raise ValueError(f'Not a base table: {name}')
            for overlay in ('video_digest_overlay_rows', 'question_graph_overlay_rows'):
                if target.execute('SELECT to_regclass(%s) IS NOT NULL', (overlay,)).fetchone()[0] and \
                        target.execute(f'SELECT 1 FROM {overlay} WHERE table_name=%s LIMIT 1', (name,)).fetchone():
                    raise ValueError(f'Overlay rows exist for {name}')
            target.execute('INSERT INTO legacy_supplement_tables VALUES (%s,%s,%s,%s)', (name, Jsonb(row[0]), row[1], row[2]))
            target.execute('INSERT INTO legacy_supplement_rows SELECT table_name,row_ordinal,row_data FROM legacy_snapshot_rows '
                           'WHERE table_name=%s', (name,))
            target.execute('INSERT INTO legacy_adopted_tables VALUES (%s)', (name,))
            if target.execute('SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s', (name,)).fetchone()[0] != row[2]:
                raise ValueError(f'Adopted row count differs: {name}')
            counts[name] = row[2]
        return counts

"""Document metadata for aggregations (D-343): source type, source id and publication time of every ledger document,
without its text, in a plain PG table rebuilt from the ledger view.

The ledger keeps a document as one JSON row with its whole markdown, so counting documents by date or source reads
every text (the US briefing's source status: 0.2 s for 15k Telegram rows). This table holds only what aggregations
need. It is derived, never written by anything else: `refresh` compares the projection version it was built at with
the current one and, when they differ, reads the view once and applies only the changed rows in one transaction
(a reader keeps the previous complete table meanwhile). `current(pg)` says whether a reader may use it.

  document_meta(doc_id, source_type, source_id, published_at)  +  document_meta_state(version, refreshed_at, rows)
"""
import time

TABLE = 'document_meta'
STATE = 'document_meta_state'


def initialize(conn):
    """The table, its indexes and its state row (idempotent; an autocommit connection is not required)."""
    conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} (doc_id BIGINT PRIMARY KEY, source_type TEXT, source_id TEXT, '
                 'published_at TEXT)')
    conn.execute(f'CREATE INDEX IF NOT EXISTS {TABLE}_published ON {TABLE} (published_at COLLATE "C")')
    conn.execute(f'CREATE INDEX IF NOT EXISTS {TABLE}_source ON {TABLE} (source_type, lower(source_id) text_pattern_ops)')
    conn.execute(f'CREATE TABLE IF NOT EXISTS {STATE} (singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton), '
                 'version TEXT, refreshed_at TIMESTAMPTZ, rows INTEGER, seconds REAL)')
    conn.execute(f'INSERT INTO {STATE} (singleton) VALUES (TRUE) ON CONFLICT DO NOTHING')


def exists(conn):
    return conn.execute('SELECT to_regclass(%s)', (STATE,)).fetchone()[0] is not None


def current(conn):
    """True when the table was built at the ledger's current version (readers fall back to the view otherwise)."""
    from pipeline.postgres_legacy_projection import projection_version
    if not exists(conn):
        return False
    built = conn.execute(f'SELECT version FROM {STATE}').fetchone()
    return bool(built and built[0] == projection_version(conn))


def refresh(conn, *, force=False):
    """{'changed': rows written or removed, 'rows', 'seconds'} or None when already current. One transaction: the
    version is read inside it, so a publication landing meanwhile only makes the next refresh run."""
    from pipeline.postgres_legacy_projection import projection_version
    started = time.perf_counter()
    with conn.transaction():
        conn.execute('SET LOCAL jit = off')
        version = projection_version(conn)
        built = conn.execute(f'SELECT version FROM {STATE} FOR UPDATE').fetchone()
        if built and built[0] == version and not force:
            return None
        conn.execute('CREATE TEMP TABLE document_meta_next ON COMMIT DROP AS '
                     "SELECT (row_data->>'id')::bigint doc_id, row_data->>'source_type' source_type, "
                     "row_data->>'source_id' source_id, row_data->>'published_at' published_at "
                     "FROM legacy_snapshot_rows WHERE table_name='raw_documents'")
        changed = conn.execute(
            f'INSERT INTO {TABLE} AS m SELECT * FROM document_meta_next ON CONFLICT (doc_id) DO UPDATE SET '
            'source_type=excluded.source_type, source_id=excluded.source_id, published_at=excluded.published_at '
            'WHERE (m.source_type, m.source_id, m.published_at) IS DISTINCT FROM '
            '(excluded.source_type, excluded.source_id, excluded.published_at)').rowcount
        changed += conn.execute(f'DELETE FROM {TABLE} m WHERE NOT EXISTS '
                                '(SELECT 1 FROM document_meta_next n WHERE n.doc_id = m.doc_id)').rowcount
        rows = conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone()[0]
        seconds = time.perf_counter() - started
        conn.execute(f'UPDATE {STATE} SET version=%s, refreshed_at=now(), rows=%s, seconds=%s', (version, rows, seconds))
    return {'changed': changed, 'rows': rows, 'seconds': round(seconds, 2)}

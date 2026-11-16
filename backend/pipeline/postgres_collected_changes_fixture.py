"""Carry collector changes to existing documents into the single-path candidate (interim path).

Only the document tables the ingest/call/narrative/causal jobs rewrite are
compared, by id, between the work copy's starting state and its end state; new
ids still go through `postgres_collected_documents_fixture.publish`. A changed
base document becomes a document revision, the same shape a published video
digest uses: its raw row replaces the base row at the same ordinal, its
enrichments and links replace the base ones (`video_projection_overrides`
hides them), and detail and list documents are rebuilt by the legacy SQLite
reader from the work copy. A document the candidate itself changed since the
copy was taken is not overwritten: its three versions (run start, collected,
candidate) are kept in `collected_change_conflicts`, and `reprocess_conflicts`
merges them field by field later, so the change is never lost; only a field
both sides changed differently is left as `needs_review`. Changes this path
cannot publish yet (deleted documents, revisions of candidate-collected
documents) are kept the same way as `unsupported`, never counted as published.
Comparing and publishing load whole tables, so they run only in a one-shot
container (`scripts/refactor_run_collector_once.sh`), never in the preview API.
"""
import hashlib
import json
import os
import sqlite3

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import GRAPH_LOCK, _guard

LINK_OFFSET = 1_000_000_000  # same ordinal space as collected publications


def _require_oneshot():
    if os.environ.get('EXPLORER_ONESHOT') != '1':
        raise RuntimeError('Run collector comparison only through scripts/refactor_run_collector_once.sh')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _documents(work, floor):
    """Per existing document: hashes of its raw row, enrichments and links."""
    work_rows = lambda sql: [dict(zip([c[0] for c in cursor.description], row)) for cursor in [work.execute(sql, (floor,))] for row in cursor]
    state = {}
    for row in work_rows('SELECT * FROM raw_documents WHERE id <= ?'):
        state[row['id']] = {'raw': _digest(row), 'enrichments': [], 'links': []}
    for row in work_rows('SELECT * FROM enrichments WHERE doc_id <= ? ORDER BY id'):
        if row['doc_id'] in state:
            state[row['doc_id']]['enrichments'].append(_digest(row))
    for row in work_rows('SELECT doc_id,entity_id,link_type,confidence FROM entity_links WHERE doc_id <= ? ORDER BY id'):
        if row['doc_id'] in state:
            state[row['doc_id']]['links'].append(_digest(row))  # link ids are reissued on re-linking
    return state


def capture(work, document_floor):
    """Record the work copy's documents before the collector runs."""
    _require_oneshot()
    return _documents(work, document_floor)


def changed_documents(work, before, document_floor):
    _require_oneshot()
    after = _documents(work, document_floor)
    changed = sorted(ident for ident, state in after.items() if before.get(ident) not in (None, state))
    removed = sorted(set(before) - set(after))
    return changed, removed


READER_TABLES = ('raw_documents', 'enrichments', 'entity_links', 'entities', 'telegram_channels', 'blog_sources',
                 'youtube_channels', 'scrap_links', 'youtube_digest_jobs')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('collected_change_conflicts')").fetchone()[0] is not None:
            raise ValueError('Collected change conflicts already initialized')
        conn.execute('CREATE TABLE collected_change_conflicts (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,'
                     'run_id TEXT NOT NULL,document_id BIGINT NOT NULL,before_state JSONB NOT NULL,collected_state JSONB NOT NULL,'
                     "candidate_state JSONB NOT NULL,status TEXT NOT NULL DEFAULT 'pending' "
                     "CHECK(status IN ('pending','merged','needs_review','unsupported')),"
                     'fields JSONB,reason TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),resolved_at TIMESTAMPTZ)')


def _sqlite_state(db, ident):
    rows = lambda sql: [dict(zip([c[0] for c in cursor.description], row)) for cursor in [db.execute(sql, (ident,))] for row in cursor]
    raw = rows('SELECT * FROM raw_documents WHERE id=?')
    return {'raw': raw[0] if raw else None, 'enrichments': rows('SELECT * FROM enrichments WHERE doc_id=? ORDER BY id'),
            'links': rows('SELECT * FROM entity_links WHERE doc_id=? ORDER BY id')}


def _pg_state(conn, ident):
    rows = lambda table, key: [row for (row,) in conn.execute(
        f"SELECT row_data FROM legacy_snapshot_rows WHERE table_name='{table}' AND row_data->>'{key}'=%s "
        "ORDER BY (row_data->>'id')::bigint", (str(ident),))]
    raw = rows('raw_documents', 'id')
    return {'raw': raw[0] if len(raw) == 1 else None, 'enrichments': rows('enrichments', 'doc_id'),
            'links': rows('entity_links', 'doc_id')}


def _fingerprint(state):
    link = lambda row: {k: row.get(k) for k in ('doc_id', 'entity_id', 'link_type', 'confidence')}
    return (_digest(state['raw']), [_digest(row) for row in state['enrichments']], [_digest(link(row)) for row in state['links']])


def _pick(base, collected, current, name, conflicts):
    if collected == base:
        return current
    if current == base or current == collected:
        return collected
    conflicts.append(name)
    return current


def _merge_rows(base, collected, current, name, conflicts):
    """Field-wise three-way merge of one row (None = absent)."""
    if collected == base or current == base or collected == current or None in (base, collected, current):
        return _pick(base, collected, current, name, conflicts)
    return {key: _pick(base.get(key), collected.get(key), current.get(key), f'{name}.{key}', conflicts)
            for key in dict.fromkeys([*current, *collected])}


def _merge(before, collected, current):
    """Three-way merge of a document state; returns (merged state, conflicting fields)."""
    conflicts = []
    raw = _merge_rows(before['raw'], collected['raw'], current['raw'], 'raw', conflicts)
    by_id = lambda rows: {row['id']: row for row in rows}
    b, c, p = by_id(before['enrichments']), by_id(collected['enrichments']), by_id(current['enrichments'])
    enrichments = [row for ident in sorted(set(b) | set(c) | set(p))
                   if (row := _merge_rows(b.get(ident), c.get(ident), p.get(ident), f'enrichments.{ident}', conflicts)) is not None]
    by_key = lambda rows: {(row['entity_id'], row['link_type']): row for row in rows}
    b, c, p = by_key(before['links']), by_key(collected['links']), by_key(current['links'])
    confidence = lambda row: None if row is None else row.get('confidence')
    links = []
    for key in [*p, *(key for key in c if key not in p), *(key for key in b if key not in p and key not in c)]:
        chosen = _pick(confidence(b.get(key)), confidence(c.get(key)), confidence(p.get(key)), f'links.{key[0]}.{key[1]}', conflicts)
        present = _pick(key in b, key in c, key in p, f'links.{key[0]}.{key[1]}', conflicts)
        if present:
            links.append({**(p.get(key) or c.get(key)), 'confidence': chosen})
    return {'raw': raw, 'enrichments': enrichments, 'links': links}, conflicts


def _document_db(conn, state):
    """A private SQLite holding just what the legacy reader needs for one document state."""
    db = sqlite3.connect(':memory:')
    meta = dict((name, (columns, ddl)) for name, columns, ddl in conn.execute(
        'SELECT table_name,columns,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(READER_TABLES),)))
    ident = state['raw']['id']
    linked = [str(row['entity_id']) for row in state['links']]
    sources = {'raw_documents': [state['raw']], 'enrichments': state['enrichments'], 'entity_links': state['links'],
               'entities': [row for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entities' "
                                                          "AND row_data->>'id'=ANY(%s)", (linked,))],
               'youtube_digest_jobs': [row for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE "
                                                                     "table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s", (str(ident),))]}
    for name in READER_TABLES:
        columns, ddl = meta[name]
        db.execute(ddl)
        data = sources[name] if name in sources else [row for (row,) in conn.execute(
            'SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal', (name,))]
        db.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * len(columns))})', [[row.get(c) for c in columns] for row in data])
    db.row_factory = sqlite3.Row
    return db


def _write(conn, ident, ordinal, state, reader_db):
    from pipeline.document_read import _read_sqlite_documents
    from pipeline.postgres_collected_documents_fixture import order_scale
    known = {row[0] for row in conn.execute("SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='entities' "
                                            "AND row_data->>'id'=ANY(%s)", ([str(row['entity_id']) for row in state['links']],))}
    if {str(row['entity_id']) for row in state['links']} - known:
        return 'links to entities not published yet'
    doc = next(iter(_read_sqlite_documents(reader_db, [ident])))
    if doc is None:
        return 'unreadable'
    detail = doc.model_dump(mode='json')
    listed = {**detail, 'digest_status': None, 'digest_error': None, 'video_digest': None, 'transcript': None}
    listing = conn.execute('SELECT ordinal FROM document_list_projection WHERE document_id=%s ORDER BY ordinal LIMIT 1',
                           (ident,)).fetchone()
    conn.execute('INSERT INTO video_projection_overrides VALUES(%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET '
                 'detail_document=excluded.detail_document,list_ordinal=excluded.list_ordinal,list_document=excluded.list_document',
                 (ident, Jsonb(detail), listing[0] // order_scale(conn) if listing else -ident, Jsonb(listed)))
    conn.execute("INSERT INTO video_digest_overlay_rows VALUES('raw_documents',%s,%s) ON CONFLICT(table_name,row_ordinal) "
                 'DO UPDATE SET row_data=excluded.row_data', (ordinal, Jsonb(state['raw'])))
    conn.execute("DELETE FROM video_digest_overlay_rows WHERE table_name IN ('enrichments','entity_links') "
                 "AND row_data->>'doc_id'=%s", (str(ident),))
    for table, key in (('enrichments', 'enrichments'), ('entity_links', 'links')):
        for row in state[key]:
            conn.execute('INSERT INTO video_digest_overlay_rows VALUES (%s,%s,%s)', (table, -LINK_OFFSET - row['id'], Jsonb(row)))
    return None


def _base_ordinal(conn, ident):
    visible = conn.execute("SELECT row_ordinal FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                           "AND row_data->>'id'=%s", (str(ident),)).fetchall()
    if len(visible) != 1:
        return None, 'missing'
    if visible[0][0] < 0 or conn.execute('SELECT 1 FROM collected_publications WHERE document_id=%s', (ident,)).fetchone():
        return None, 'collected document revisions are not supported yet'
    return visible[0][0], None


def publish_revisions(conn, work, origin, doc_ids, *, run_id):
    """Publish the work copy's version of changed existing documents in one transaction.

    `origin` is the read-only snapshot the work copy was taken from (held open for the run).
    """
    _require_oneshot()
    _guard(conn)
    work.row_factory = sqlite3.Row  # the legacy reader indexes rows by name
    published, kept = [], []

    def keep(ident, before, collected, current, status, reason):
        # Not published: all three versions stay for a later merge or a later supported path.
        conn.execute('INSERT INTO collected_change_conflicts(run_id,document_id,before_state,collected_state,candidate_state,'
                     'status,reason) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                     (run_id, ident, Jsonb(before), Jsonb(collected), Jsonb(current), status, reason))
        kept.append((ident, status, reason))

    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        for ident in doc_ids:
            before, collected, current = _sqlite_state(origin, ident), _sqlite_state(work, ident), _pg_state(conn, ident)
            ordinal, reason = _base_ordinal(conn, ident)
            if collected['raw'] is None:
                keep(ident, before, collected, current, 'unsupported', 'deleted by the collector')
            elif reason:
                keep(ident, before, collected, current, 'unsupported', reason)
            elif _fingerprint(current) != _fingerprint(before):
                keep(ident, before, collected, current, 'pending', 'changed in the candidate meanwhile')
            elif reason := _write(conn, ident, ordinal, collected, work):
                keep(ident, before, collected, current, 'pending', reason)
            else:
                published.append(ident)
    return {'published': published, 'kept': kept}


def reprocess_conflicts(conn):
    """Merge every pending conflict onto the candidate's current state; run before each collection."""
    _require_oneshot()
    _guard(conn)
    merged, review, waiting = [], [], []
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        for cid, ident, before, collected in conn.execute(
                "SELECT id,document_id,before_state,collected_state FROM collected_change_conflicts WHERE status='pending' "
                'ORDER BY id FOR UPDATE').fetchall():
            ordinal, reason = _base_ordinal(conn, ident)
            if reason:
                conn.execute('UPDATE collected_change_conflicts SET reason=%s WHERE id=%s', (reason, cid))
                waiting.append((cid, reason))
                continue
            state, fields = _merge(before, collected, _pg_state(conn, ident))
            if fields:
                conn.execute("UPDATE collected_change_conflicts SET status='needs_review',fields=%s,resolved_at=now() WHERE id=%s",
                             (Jsonb(fields), cid))
                review.append((cid, ident, fields))
                continue
            reason = _write(conn, ident, ordinal, state, _document_db(conn, state))
            if reason:
                conn.execute('UPDATE collected_change_conflicts SET reason=%s WHERE id=%s', (reason, cid))
                waiting.append((cid, reason))
                continue
            conn.execute("UPDATE collected_change_conflicts SET status='merged',resolved_at=now() WHERE id=%s", (cid,))
            merged.append((cid, ident))
    return {'merged': merged, 'needs_review': review, 'waiting': waiting}


def publish_run(conn, work, origin, before, *, document_floor, entity_floor, keyword_floor, relation_floor, run_id):
    """One collection run in one transaction: new rows first (so new entities exist), then revisions."""
    from pipeline.postgres_collected_documents_fixture import publish
    _require_oneshot()
    changed, removed = changed_documents(work, before, document_floor)
    with conn.transaction():
        added = publish(conn, work, document_floor=document_floor, entity_floor=entity_floor,
                        keyword_floor=keyword_floor, relation_floor=relation_floor)
        revised = publish_revisions(conn, work, origin, [*changed, *removed], run_id=run_id)
    return {'added': [doc['id'] for doc in added], 'revised': revised['published'], 'kept': revised['kept']}


def unprocessed(conn):
    """What collector changes are still not in the candidate, by status."""
    return conn.execute("SELECT status,count(*),array_agg(document_id ORDER BY id) FROM collected_change_conflicts "
                        "WHERE status<>'merged' GROUP BY status ORDER BY status").fetchall()

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
cannot publish yet (deleted documents) are kept the same way as `unsupported`, never counted as published. A
document the candidate itself collected is revised where its rows live (`_write_collected`).
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
                     "fields JSONB,reason TEXT,target_table TEXT NOT NULL DEFAULT 'raw_documents',"
                     'created_at TIMESTAMPTZ NOT NULL DEFAULT now(),resolved_at TIMESTAMPTZ)')


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


# Per-document copies a revised document must replace too (keyed by document_id).
COPIES = ('timeline_source_projection', 'timeline_source_metadata', 'document_entity_order')


def initialize_revision_copies(conn):
    """Revised documents (any `video_projection_overrides` row) read these copies from `revised_*` tables."""
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('revised_document_entity_order')").fetchone()[0] is not None:
            raise ValueError('Revision copies already initialized')
        for view in COPIES:
            columns = ','.join(row[0] for row in conn.execute(
                'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s '
                'ORDER BY ordinal_position', (view,)))
            conn.execute(f'CREATE TABLE revised_{view} AS SELECT {columns} FROM {view} WHERE false')
            # Documents revised before this existed keep exactly what they show now.
            conn.execute(f'INSERT INTO revised_{view} SELECT {columns} FROM {view} '
                         'WHERE document_id IN (SELECT document_id FROM video_projection_overrides)')
            definition = conn.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', (view,)).fetchone()[0]
            conn.execute(f'CREATE OR REPLACE VIEW {view} AS SELECT {columns} FROM ({definition.rstrip().rstrip(";")}) v '
                         'WHERE NOT EXISTS (SELECT 1 FROM video_projection_overrides o WHERE o.document_id=v.document_id) '
                         f'UNION ALL SELECT {columns} FROM revised_{view} r '  # only while the revision stands
                         'WHERE EXISTS (SELECT 1 FROM video_projection_overrides o WHERE o.document_id=r.document_id)')


def _write_copies(conn, ident, state, detail, timeline):
    """Rebuild a revised document's timeline row, timeline metadata and entity order from its new state."""
    if conn.execute("SELECT to_regclass('revised_document_entity_order')").fetchone()[0] is None:
        return
    for view in COPIES:
        conn.execute(f'DELETE FROM revised_{view} WHERE document_id=%s', (ident,))
    counts = {}
    for position, tag in enumerate(detail['entities']):  # same occurrence numbering as the snapshot loader
        key = (tag['entity_id'], tag['link_type'], tag['confidence'])
        conn.execute('INSERT INTO revised_document_entity_order VALUES (%s,%s,%s,%s,%s,%s)', (ident, position, *key, counts.get(key, 0)))
        counts[key] = counts.get(key, 0) + 1
    enrichment = max(state['enrichments'], key=lambda row: (row.get('enriched_at') or '', row['id']), default=None)
    conn.execute('INSERT INTO revised_timeline_source_metadata VALUES (%s,%s,%s)',
                 (ident, enrichment and enrichment['id'], Jsonb([{'entity_id': row['entity_id'], 'link_type': row['link_type'],
                                                                 'confidence': row['confidence']} for row in state['links']])))
    if timeline:  # the source's place in the timeline does not move; its content does
        row_id, occurred, millis, channel, platform, label, document = timeline
        raw = state['raw']
        conn.execute('INSERT INTO revised_timeline_source_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (row_id, ident, occurred, millis, channel, platform, sorted({tag['name'] for tag in detail['entities']}), label,
                      (raw.get('title') or raw.get('markdown') or '')[:180],
                      Jsonb({**detail, 'published_at': document.get('published_at')})))


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
    timeline = conn.execute('SELECT id,occurred_at,sort_millis,channel,platform,time_label,document FROM timeline_source_projection '
                            'WHERE document_id=%s', (ident,)).fetchone()  # before the override hides the original row
    conn.execute('INSERT INTO video_projection_overrides VALUES(%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET '
                 'detail_document=excluded.detail_document,list_ordinal=excluded.list_ordinal,list_document=excluded.list_document',
                 (ident, Jsonb(detail), listing[0] // order_scale(conn) if listing else -ident, Jsonb(listed)))
    _write_copies(conn, ident, state, detail, timeline)
    conn.execute("INSERT INTO video_digest_overlay_rows VALUES('raw_documents',%s,%s) ON CONFLICT(table_name,row_ordinal) "
                 'DO UPDATE SET row_data=excluded.row_data', (ordinal, Jsonb(state['raw'])))
    conn.execute("DELETE FROM video_digest_overlay_rows WHERE table_name IN ('enrichments','entity_links') "
                 "AND row_data->>'doc_id'=%s", (str(ident),))
    for table, key in (('enrichments', 'enrichments'), ('entity_links', 'links')):
        for row in state[key]:
            conn.execute('INSERT INTO video_digest_overlay_rows VALUES (%s,%s,%s)', (table, -LINK_OFFSET - row['id'], Jsonb(row)))
    return None


def _base_ordinal(conn, ident):
    """(ordinal, None) of a base document, (None, 'collected') of one the candidate collected, or (None, reason)."""
    visible = conn.execute("SELECT row_ordinal FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                           "AND row_data->>'id'=%s", (str(ident),)).fetchall()
    if len(visible) != 1:
        return None, 'missing'
    if visible[0][0] < 0 or conn.execute('SELECT 1 FROM collected_publications WHERE document_id=%s', (ident,)).fetchone():
        return None, 'collected'
    return visible[0][0], None


def _write_collected(conn, ident, state):
    """A revision of a document the candidate collected: its rows are replaced where they live (as a video digest of a
    collected video does), not hidden under a base override. Its place in the list and timeline does not move."""
    from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
    known = {row[0] for row in conn.execute("SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='entities' "
                                            "AND row_data->>'id'=ANY(%s)", ([str(row['entity_id']) for row in state['links']],))}
    if {str(row['entity_id']) for row in state['links']} - known:
        return 'links to entities not published yet'
    published = conn.execute('SELECT enrichment_ids,link_ids FROM collected_publications WHERE document_id=%s FOR UPDATE',
                             (ident,)).fetchone()
    if published is None:
        return 'not recorded as collected'
    conn.execute("UPDATE video_digest_overlay_rows SET row_data=%s WHERE table_name='raw_documents' AND row_ordinal=%s",
                 (Jsonb(state['raw']), -ident))
    for table, ids in (('enrichments', published[0]), ('entity_links', published[1])):
        conn.execute('DELETE FROM video_digest_overlay_rows WHERE table_name=%s AND row_ordinal=ANY(%s)',
                     (table, [-LINK_OFFSET - i for i in ids]))
    for table, key in (('enrichments', 'enrichments'), ('entity_links', 'links')):
        for row in state[key]:
            conn.execute('INSERT INTO video_digest_overlay_rows VALUES (%s,%s,%s)', (table, -LINK_OFFSET - row['id'], Jsonb(row)))
    conn.execute('UPDATE collected_publications SET enrichment_ids=%s,link_ids=%s WHERE document_id=%s',
                 ([row['id'] for row in state['enrichments']], [row['id'] for row in state['links']], ident))
    conn.execute('DELETE FROM collected_document_entity_order WHERE document_id=%s', (ident,))
    for position, link in enumerate(state['links']):
        conn.execute('INSERT INTO collected_document_entity_order VALUES (%s,%s,%s,%s,%s,0)',
                     (ident, position, link['entity_id'], link['link_type'], link['confidence']))
    doc = PostgreSQLRawDocumentReader(None).get_in_transaction(conn, ident)
    if doc is None:
        return 'unreadable'
    detail = doc.model_dump(mode='json')
    conn.execute('UPDATE collected_document_projection SET detail_document=%s WHERE id=%s', (Jsonb(detail), ident))
    conn.execute('UPDATE collected_document_list_projection SET list_document=%s WHERE document_id=%s', (Jsonb(detail), ident))
    timeline = conn.execute('SELECT occurred_at FROM collected_timeline_source_projection WHERE document_id=%s', (ident,)).fetchone()
    if timeline:
        raw = state['raw']
        conn.execute('UPDATE collected_timeline_source_projection SET topic_names=%s,preview=%s,document=%s WHERE document_id=%s',
                     (sorted({link.name for link in doc.entities}), (raw.get('title') or raw.get('markdown') or '')[:180],
                      Jsonb({**detail, 'published_at': _iso_utc(timeline[0])}), ident))
        enrichment = max(state['enrichments'], key=lambda row: (row.get('enriched_at') or '', row['id']), default=None)
        conn.execute('UPDATE collected_timeline_source_metadata SET enrichment_id=%s,entity_order=%s WHERE document_id=%s',
                     (enrichment and enrichment['id'], Jsonb([{'entity_id': row['entity_id'], 'link_type': row['link_type'],
                                                             'confidence': row['confidence']} for row in state['links']]), ident))
    return None


def _iso_utc(value):
    """A timestamptz read back from PG as the ISO text the first publication stored (UTC, `+00:00`)."""
    from datetime import datetime, timezone
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value


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
            elif reason and reason != 'collected':
                keep(ident, before, collected, current, 'unsupported', reason)
            elif _fingerprint(current) != _fingerprint(before):
                keep(ident, before, collected, current, 'pending', 'changed in the candidate meanwhile')
            elif reason := (_write_collected(conn, ident, collected) if reason == 'collected'
                            else _write(conn, ident, ordinal, collected, work)):
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
        for cid, ident, table, before, collected in conn.execute(
                "SELECT id,document_id,target_table,before_state,collected_state FROM collected_change_conflicts "
                "WHERE status='pending' ORDER BY id FOR UPDATE").fetchall():
            if table != 'raw_documents':  # one graph row: field-wise merge onto its current version
                fields = []
                ordinal, current = _pg_graph_row(conn, table, ident)
                row = _merge_rows(before, collected, current, table, fields)
                if fields:
                    conn.execute("UPDATE collected_change_conflicts SET status='needs_review',fields=%s,resolved_at=now() "
                                 'WHERE id=%s', (Jsonb(fields), cid))
                    review.append((cid, ident, fields))
                    continue
                _apply_graph(conn, table, ident, ordinal, row)
                conn.execute("UPDATE collected_change_conflicts SET status='merged',resolved_at=now() WHERE id=%s", (cid,))
                merged.append((cid, ident))
                continue
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


def publish_run(conn, work, origin, before, *, document_floor, entity_floor, keyword_floor, relation_floor, run_id,
                graph=None):
    """One collection run in one transaction: new rows first (so new entities exist), then revisions.

    `graph` is `capture_graph(work)` taken with `before`; without it existing graph rows are not compared.
    """
    from pipeline.postgres_collected_documents_fixture import publish
    _require_oneshot()
    changed, removed = changed_documents(work, before, document_floor)
    with conn.transaction():
        added = publish(conn, work, document_floor=document_floor, entity_floor=entity_floor,
                        keyword_floor=keyword_floor, relation_floor=relation_floor)
        graph_result = publish_graph_revisions(conn, work, origin, *graph, run_id=run_id) if graph else None
        revised = publish_revisions(conn, work, origin, [*changed, *removed], run_id=run_id)
    return {'added': [doc['id'] for doc in added], 'revised': revised['published'], 'kept': revised['kept'],
            'graph': graph_result}


def unprocessed(conn):
    """What collector changes are still not in the candidate, by status."""
    return conn.execute("SELECT target_table,status,count(*),array_agg(document_id ORDER BY id) FROM collected_change_conflicts "
                        "WHERE status<>'merged' GROUP BY 1,2 ORDER BY 1,2").fetchall()


# Graph rows the narrative/causal/curation jobs rewrite in place. Entities and keywords are
# replaced through `collected_row_revisions`; relations and edge evidence already live in the
# candidate's writable graph ledger (rows view + source table must stay identical).
GRAPH = ('entities', 'entity_keywords', 'entity_relations', 'narrative_edge_evidence')
LEDGER = {'entity_relations': 'question_graph_overlay_relations', 'narrative_edge_evidence': 'question_graph_overlay_evidence'}


def initialize_graph_revisions(conn):
    """Let collected versions replace (or remove) visible entity and keyword rows; record graph conflicts too."""
    from pipeline.postgres_legacy_projection import ensure_projection_triggers
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('collected_row_revisions')").fetchone()[0] is not None:
            raise ValueError('Graph revisions already initialized')
        conn.execute("CREATE TABLE collected_row_revisions (table_name TEXT NOT NULL CHECK(table_name IN ('entities','entity_keywords')),"
                     'row_ordinal BIGINT NOT NULL,row_data JSONB,PRIMARY KEY(table_name,row_ordinal))')
        definition = conn.execute("SELECT pg_get_viewdef(to_regclass('legacy_snapshot_rows'),true)").fetchone()[0]
        conn.execute(f'''CREATE OR REPLACE VIEW legacy_snapshot_rows AS
            SELECT v.table_name,v.row_ordinal,v.row_data FROM ({definition.rstrip().rstrip(";")}) v
            WHERE NOT EXISTS (SELECT 1 FROM collected_row_revisions r WHERE r.table_name=v.table_name AND r.row_ordinal=v.row_ordinal)
            UNION ALL SELECT table_name,row_ordinal,row_data FROM collected_row_revisions WHERE row_data IS NOT NULL''')
        conn.execute("ALTER TABLE collected_change_conflicts ADD COLUMN IF NOT EXISTS target_table TEXT NOT NULL DEFAULT 'raw_documents'")
    ensure_projection_triggers(conn)


def _graph_rows(db, table, ids=None, *, floor=None):
    sql = f'SELECT * FROM {table}' + (' WHERE id <= ?' if floor is not None else ' WHERE id = ?')
    out = {}
    for value in ([floor] if floor is not None else ids):
        cursor = db.execute(sql, (value,))
        columns = [c[0] for c in cursor.description]
        out.update({row[0]: dict(zip(columns, row)) for row in cursor})
    return out


def capture_graph(work):
    """Per graph table: id -> row hash of the work copy's rows before the collector runs."""
    _require_oneshot()
    floors = {table: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for table in GRAPH}
    return {table: {ident: _digest(row) for ident, row in _graph_rows(work, table, floor=floors[table]).items()}
            for table in GRAPH}, floors


def _pg_graph_row(conn, table, ident):
    rows = conn.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name=%s AND row_data->>'id'=%s",
                        (table, str(ident))).fetchall()
    if len(rows) > 1:
        raise ValueError(f'Duplicate visible {table} row {ident}')
    return rows[0] if rows else (None, None)


def _apply_graph(conn, table, ident, ordinal, row):
    """Write one graph row's new version (None removes it)."""
    if table in LEDGER:
        if row is None:
            conn.execute('DELETE FROM question_graph_overlay_rows WHERE table_name=%s AND row_data->>\'id\'=%s', (table, str(ident)))
            conn.execute(f'DELETE FROM {LEDGER[table]} WHERE id=%s', (ident,))
        elif ordinal is None:  # new in this run
            position = conn.execute('SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_graph_overlay_rows WHERE table_name=%s',
                                    (table,)).fetchone()[0]
            conn.execute('INSERT INTO question_graph_overlay_rows VALUES (%s,%s,%s)', (table, position, Jsonb(row)))
            conn.execute(f'INSERT INTO {LEDGER[table]}(id,source_row) VALUES (%s,%s)', (ident, Jsonb(row)))
        else:
            conn.execute("UPDATE question_graph_overlay_rows SET row_data=%s WHERE table_name=%s AND row_data->>'id'=%s",
                         (Jsonb(row), table, str(ident)))
            conn.execute(f'UPDATE {LEDGER[table]} SET source_row=%s WHERE id=%s', (Jsonb(row), ident))
    else:
        conn.execute('INSERT INTO collected_row_revisions VALUES (%s,%s,%s) ON CONFLICT (table_name,row_ordinal) '
                     'DO UPDATE SET row_data=excluded.row_data', (table, ordinal, Jsonb(row) if row is not None else None))


def publish_graph_revisions(conn, work, origin, before, floors, *, run_id):
    """Apply changed/removed existing graph rows (and new edge evidence) unless the candidate changed them meanwhile."""
    _require_oneshot()
    _guard(conn)
    applied, kept, added = [], [], []
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        for table in GRAPH:
            after = {ident: _digest(row) for ident, row in _graph_rows(work, table, floor=floors[table]).items()}
            changed = sorted(ident for ident, digest in after.items() if before[table].get(ident) not in (None, digest))
            removed = sorted(set(before[table]) - set(after))
            for ident in [*changed, *removed]:
                start = _graph_rows(origin, table, [ident]).get(ident)
                collected = _graph_rows(work, table, [ident]).get(ident)
                ordinal, current = _pg_graph_row(conn, table, ident)
                if current != start:
                    conn.execute('INSERT INTO collected_change_conflicts(run_id,document_id,target_table,before_state,collected_state,'
                                 "candidate_state,status,reason) VALUES (%s,%s,%s,%s,%s,%s,'pending','changed in the candidate meanwhile')",
                                 (run_id, ident, table, Jsonb(start), Jsonb(collected), Jsonb(current)))
                    kept.append((table, ident))
                    continue
                _apply_graph(conn, table, ident, ordinal, collected)
                applied.append((table, ident))
        # New edge evidence (the publish of new rows covers entities, keywords and relations).
        cursor = work.execute('SELECT * FROM narrative_edge_evidence WHERE id > ? ORDER BY id', (floors['narrative_edge_evidence'],))
        columns = [c[0] for c in cursor.description]
        for values in cursor.fetchall():
            row = dict(zip(columns, values))
            if _pg_graph_row(conn, 'narrative_edge_evidence', row['id'])[1] is not None:
                raise RuntimeError('narrative_edge_evidence IDs were taken while collecting; nothing published')
            _apply_graph(conn, 'narrative_edge_evidence', row['id'], None, row)
            added.append(row['id'])
    return {'applied': applied, 'kept': kept, 'evidence_added': added}

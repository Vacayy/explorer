"""Carry collector changes to existing documents into the single-path candidate (interim path).

Only the document tables the ingest/call/narrative/causal jobs rewrite are
compared, by id, between the work copy's starting state and its end state; new
ids still go through `postgres_collected_documents_fixture.publish`. A changed
base document becomes a document revision, the same shape a published video
digest uses: its raw row replaces the base row at the same ordinal, its
enrichments and links replace the base ones (`video_projection_overrides`
hides them), and detail and list documents are rebuilt by the legacy SQLite
reader from the work copy. A document the candidate itself changed since the
copy was taken is skipped and reported, never overwritten.
"""
import hashlib
import json
import sqlite3

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import GRAPH_LOCK, _guard

LINK_OFFSET = 1_000_000_000  # same ordinal space as collected publications


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
            state[row['doc_id']]['links'].append(_digest(row))
    return state


def capture(work, document_floor):
    """Record the work copy's documents before the collector runs."""
    return _documents(work, document_floor)


def changed_documents(work, before, document_floor):
    after = _documents(work, document_floor)
    changed = sorted(ident for ident, state in after.items() if before.get(ident) not in (None, state))
    removed = sorted(set(before) - set(after))
    return changed, removed


def _visible_raw(conn, ident):
    return conn.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                        "AND row_data->>'id'=%s", (str(ident),)).fetchall()


def publish_revisions(conn, work, before, doc_ids):
    """Publish the work copy's version of changed existing documents in one transaction."""
    from pipeline.document_read import _read_sqlite_documents
    from pipeline.postgres_collected_documents_fixture import order_scale
    _guard(conn)
    work.row_factory = sqlite3.Row  # the legacy reader indexes rows by name
    rows = lambda sql, *params: [dict(zip([c[0] for c in cursor.description], row))
                                 for cursor in [work.execute(sql, params)] for row in cursor]
    published, skipped = [], []
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        scale = order_scale(conn)
        for ident in doc_ids:
            raw = rows('SELECT * FROM raw_documents WHERE id=?', ident)
            visible = _visible_raw(conn, ident)
            if not raw or len(visible) != 1:
                skipped.append((ident, 'missing'))
                continue
            ordinal, current = visible[0]
            if ordinal < 0 or conn.execute('SELECT 1 FROM collected_publications WHERE document_id=%s', (ident,)).fetchone():
                skipped.append((ident, 'collected document revisions are not supported yet'))
                continue
            # The candidate's own view must still be what the collector started from.
            enrichments = [_digest(r) for r in (row for (row,) in conn.execute(
                "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='enrichments' AND row_data->>'doc_id'=%s "
                "ORDER BY (row_data->>'id')::bigint", (str(ident),)))]
            if _digest(current) != before[ident]['raw'] or enrichments != before[ident]['enrichments']:
                skipped.append((ident, 'changed in the candidate meanwhile'))
                continue
            linked = {str(row['entity_id']) for row in rows('SELECT entity_id FROM entity_links WHERE doc_id=?', ident)}
            known = {row[0] for row in conn.execute("SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='entities' "
                                                    "AND row_data->>'id'=ANY(%s)", (list(linked),))}
            if linked - known:
                skipped.append((ident, 'links to entities not published yet'))
                continue
            doc = next(iter(_read_sqlite_documents(work, [ident])))
            if doc is None:
                skipped.append((ident, 'unreadable in the work copy'))
                continue
            detail = doc.model_dump(mode='json')
            listed = {**detail, 'digest_status': None, 'digest_error': None, 'video_digest': None, 'transcript': None}
            listing = conn.execute('SELECT ordinal FROM document_list_projection WHERE document_id=%s ORDER BY ordinal LIMIT 1',
                                   (ident,)).fetchone()
            conn.execute('INSERT INTO video_projection_overrides VALUES(%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET '
                         'detail_document=excluded.detail_document,list_ordinal=excluded.list_ordinal,'
                         'list_document=excluded.list_document',
                         (ident, Jsonb(detail), listing[0] // scale if listing else -ident, Jsonb(listed)))
            conn.execute("INSERT INTO video_digest_overlay_rows VALUES('raw_documents',%s,%s) ON CONFLICT(table_name,row_ordinal) "
                         'DO UPDATE SET row_data=excluded.row_data', (ordinal, Jsonb(raw[0])))
            conn.execute("DELETE FROM video_digest_overlay_rows WHERE table_name IN ('enrichments','entity_links') "
                         "AND row_data->>'doc_id'=%s", (str(ident),))
            for table in ('enrichments', 'entity_links'):
                for row in rows(f'SELECT * FROM {table} WHERE doc_id=? ORDER BY id', ident):
                    conn.execute('INSERT INTO video_digest_overlay_rows VALUES (%s,%s,%s)', (table, -LINK_OFFSET - row['id'], Jsonb(row)))
            published.append(ident)
    return {'published': published, 'skipped': skipped}

"""Publish newly collected documents into the single-path candidate, in place.

Interim collector path (not the target design). An unchanged legacy collector
runs on a writable copy of the candidate's projection file, so it already sees
published videos, overlay entities and the owner's records. Afterwards only the
documents whose id is above the copy's starting high-water mark are published
here, with the same feed, timeline and detail rules as the note overlay
publisher (`postgres_note_overlay_fixture`). Rows live in `collected_*` tables
unioned into the snapshot views; the base generation is never changed.
Documents of any publish time take their time slot, as in the legacy feed
(published_at DESC): `scale_orders` spreads the base list ordinals and filter
positions by ORDER_SCALE, and every publish re-spaces all collected rows evenly
inside the gap between their base neighbours (after base rows of the same
time). A gap holds ORDER_SCALE-1 documents; a fuller gap fails closed.
"""
from bisect import bisect_left
from collections import defaultdict

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import GRAPH_LOCK, _guard

VIEWS = ('document_projection', 'document_list_projection', 'document_filter_order', 'timeline_source_projection',
         'timeline_source_metadata', 'document_entity_order')
ORDER_SCALE = 1 << 20


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('collected_document_projection')").fetchone()[0] is not None:
            raise ValueError('Collected document overlay already initialized')
        for view in VIEWS:
            columns = [row[0] for row in conn.execute(
                'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s '
                'ORDER BY ordinal_position', (view,))]
            quoted = ','.join(f'"{column}"' for column in columns)
            definition = conn.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', (view,)).fetchone()[0]
            conn.execute(f'CREATE TABLE collected_{view} AS SELECT {quoted} FROM {view} WHERE false')
            conn.execute(f'CREATE OR REPLACE VIEW {view} AS {definition.rstrip().rstrip(";")} '
                         f'UNION ALL SELECT {quoted} FROM collected_{view}')
        # Counts the search snapshot and list reader check against the visible rows.
        definition = conn.execute("SELECT pg_get_viewdef(to_regclass('snapshot_metadata'),true)").fetchone()[0]
        types = dict(conn.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=current_schema() "
                                  "AND table_name='snapshot_metadata'").fetchall())
        conn.execute('CREATE TABLE collected_snapshot_base AS SELECT * FROM snapshot_metadata')
        conn.execute(f'''CREATE OR REPLACE VIEW snapshot_metadata AS
            SELECT singleton,snapshot_at,source_observed_at,loaded_at,
                   (document_count + (SELECT count(*) FROM collected_document_projection))::{types['document_count']} AS document_count,
                   (list_row_count + (SELECT count(*) FROM collected_document_list_projection))::{types['list_row_count']} AS list_row_count,
                   generation_id
            FROM ({definition.rstrip().rstrip(";")}) base''')
        conn.execute('DROP TABLE collected_snapshot_base')
        # What each publish added, so a candidate-only document can be withdrawn by ID
        # (MacBook keeps collecting in the same ID space; see the cut-over checklist).
        conn.execute('CREATE TABLE collected_publications (document_id BIGINT PRIMARY KEY,list_ordinal BIGINT,'
                     'enrichment_ids BIGINT[] NOT NULL,link_ids BIGINT[] NOT NULL,entity_ids BIGINT[] NOT NULL,'
                     'keyword_ids BIGINT[] NOT NULL,relation_ids BIGINT[] NOT NULL,'
                     'published_at TIMESTAMPTZ NOT NULL DEFAULT now())')


def scale_orders(conn):
    """Spread base list ordinals and filter positions so collected rows fit between them."""
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('collected_order_scale')").fetchone()[0] is not None:
            raise ValueError('Orders already scaled')
        if conn.execute('SELECT EXISTS(SELECT 1 FROM collected_document_list_projection) '
                        'OR EXISTS(SELECT 1 FROM collected_document_filter_order)').fetchone()[0]:
            raise ValueError('Withdraw collected documents before scaling')
        for view, columns, scaled in (
                ('document_list_projection', 'ordinal,document_id,list_document',
                 f'b.ordinal*{ORDER_SCALE} AS ordinal,b.document_id,b.list_document'),
                ('document_filter_order', 'filter_key,position,list_ordinal',
                 f'b.filter_key,b.position*{ORDER_SCALE} AS position,b.list_ordinal*{ORDER_SCALE} AS list_ordinal')):
            definition = conn.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', (view,)).fetchone()[0]
            head, _, tail = definition.rstrip().rstrip(';').rpartition('UNION ALL')
            if f'collected_{view}' not in tail or f'collected_{view}' in head:
                raise ValueError(f'Unexpected view shape: {view}')
            conn.execute(f'CREATE OR REPLACE VIEW {view} AS SELECT {scaled} FROM ({head}) b '
                         f'UNION ALL SELECT {columns} FROM collected_{view}')
        conn.execute('CREATE TABLE collected_order_scale (scale BIGINT NOT NULL)')
        conn.execute('INSERT INTO collected_order_scale VALUES (%s)', (ORDER_SCALE,))


def order_scale(conn):
    """1 until `scale_orders` ran; base ordinals in the views are multiplied by it."""
    if conn.execute("SELECT to_regclass('collected_order_scale')").fetchone()[0] is None:
        return 1
    return conn.execute('SELECT scale FROM collected_order_scale').fetchone()[0]


def _slots(base, items, scale):
    """Order values for items (key, time, id) among base (value, time) sorted by value, time descending.

    An item goes after base rows of the same or a later time; items sharing a gap
    are spaced evenly in (time DESC, id ASC) order.
    """
    times = [time or '' for _, time in base]
    if any(a < b for a, b in zip(times, times[1:])):
        raise ValueError('Base order is not newest first')
    ascending = times[::-1]
    gaps = defaultdict(list)
    for key, time, ident in items:
        gaps[len(times) - bisect_left(ascending, time or '')].append((key, time or '', ident))
    values = {}
    for index, members in gaps.items():
        members.sort(key=lambda item: item[2])
        members.sort(key=lambda item: item[1], reverse=True)
        upper = base[index - 1][0] if index > 0 else None
        lower = base[index][0] if index < len(base) else None
        count = len(members)
        if upper is not None and lower is not None:
            step = (lower - upper) // (count + 1)
            if step < 1:
                raise ValueError('No room left between two listed documents')
            spots = [upper + step * k for k in range(1, count + 1)]
        elif lower is not None:
            spots = [lower - scale * (count + 1 - k) for k in range(1, count + 1)]
        else:
            spots = [(upper if upper is not None else 0) + scale * k for k in range(1, count + 1)]
        values.update({key: spot for (key, _, _), spot in zip(members, spots)})
    return values


def _place(conn, pending):
    """Re-space every collected list row and filter row; pending maps new document IDs to filter keys."""
    scale = order_scale(conn)
    if scale == 1:
        raise ValueError('Scale the base orders first')
    keys = defaultdict(list, pending)
    for key, ident in conn.execute('SELECT o.filter_key,l.document_id FROM collected_document_filter_order o '
                                   'JOIN collected_document_list_projection l ON l.ordinal=o.list_ordinal'):
        keys[ident].append(key)
    collected = conn.execute('SELECT c.document_id,d.published_at FROM collected_document_list_projection c '
                             'JOIN collected_document_projection d ON d.id=c.document_id').fetchall()
    base = conn.execute('SELECT l.ordinal,d.published_at FROM document_list_projection l JOIN document_projection d '
                        'ON d.id=l.document_id WHERE NOT EXISTS (SELECT 1 FROM collected_document_list_projection c '
                        'WHERE c.document_id=l.document_id) ORDER BY l.ordinal').fetchall()
    ordinals = _slots(base, [(ident, time, ident) for ident, time in collected], scale)
    times = dict(collected)
    filters = []
    for key in sorted({key for values in keys.values() for key in values}):
        rows = conn.execute('SELECT o.position,d.published_at FROM document_filter_order o '
                            'JOIN document_list_projection l ON l.ordinal=o.list_ordinal '
                            'JOIN document_projection d ON d.id=l.document_id WHERE o.filter_key=%s '
                            'AND NOT EXISTS (SELECT 1 FROM collected_document_list_projection c '
                            'WHERE c.document_id=l.document_id) ORDER BY o.position', (key,)).fetchall()
        members = [(ident, times[ident], ident) for ident, values in keys.items() if key in values]
        filters += [(key, position, ordinals[ident]) for ident, position in _slots(rows, members, scale).items()]
    conn.execute('DELETE FROM collected_document_filter_order')
    for ident, ordinal in ordinals.items():
        conn.execute('UPDATE collected_document_list_projection SET ordinal=%s WHERE document_id=%s', (ordinal, ident))
        conn.execute('UPDATE collected_publications SET list_ordinal=%s WHERE document_id=%s', (ordinal, ident))
    for row in filters:
        conn.execute('INSERT INTO collected_document_filter_order VALUES (%s,%s,%s)', row)


def _rows(work, table, where, params):
    columns = [row[1] for row in work.execute(f'PRAGMA table_info("{table}")')]
    return [dict(zip(columns, row)) for row in work.execute(f'SELECT * FROM "{table}" WHERE {where}', params)]


def publish(conn, work, *, document_floor, entity_floor, keyword_floor, relation_floor):
    """Publish the work copy's documents above the starting high-water marks in one transaction."""
    from pipeline.postgres_note_overlay_fixture import _new_source_details
    from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
    _guard(conn)
    docs = sorted(_rows(work, 'raw_documents', 'id > ?', (document_floor,)), key=lambda row: (row['published_at'] or '', row['id']))
    ids = [row['id'] for row in docs]
    marks = ','.join('?' * len(ids))
    enrichments = _rows(work, 'enrichments', f'doc_id IN ({marks})', ids) if ids else []
    links = _rows(work, 'entity_links', f'doc_id IN ({marks}) ORDER BY id', ids) if ids else []
    # Re-linking existing documents can add graph rows without any new document.
    entities = _rows(work, 'entities', 'id > ?', (entity_floor,))
    keywords = _rows(work, 'entity_keywords', 'id > ?', (keyword_floor,))
    relations = _rows(work, 'entity_relations', 'id > ?', (relation_floor,))
    if not (docs or entities or keywords or relations):
        return []
    reader = PostgreSQLRawDocumentReader(None)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        conn.execute('LOCK TABLE collected_document_list_projection IN EXCLUSIVE MODE')
        for table, rows in (('raw_documents', docs), ('entities', entities), ('entity_keywords', keywords),
                            ('entity_relations', relations)):
            taken = conn.execute(f"SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s AND row_data->>'id'=ANY(%s)",
                                 (table, [str(row['id']) for row in rows])).fetchone()[0]
            if taken:
                raise RuntimeError(f'{table} IDs were taken while collecting; nothing published')
        for row in docs:
            conn.execute("INSERT INTO video_digest_overlay_rows VALUES ('raw_documents',%s,%s)", (-row['id'], Jsonb(row)))
        for row in enrichments:
            conn.execute("INSERT INTO video_digest_overlay_rows VALUES ('enrichments',%s,%s)", (-1_000_000_000 - row['id'], Jsonb(row)))
        for row in links:
            conn.execute("INSERT INTO video_digest_overlay_rows VALUES ('entity_links',%s,%s)", (-1_000_000_000 - row['id'], Jsonb(row)))
        for table, rows in (('entities', entities), ('entity_keywords', keywords)):
            for row in rows:
                conn.execute('INSERT INTO video_digest_overlay_rows VALUES (%s,%s,%s)', (table, -row['id'], Jsonb(row)))
        ordinal = conn.execute("SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_graph_overlay_rows WHERE table_name='entity_relations'").fetchone()[0]
        for position, row in enumerate(relations):
            conn.execute("INSERT INTO question_graph_overlay_rows VALUES('entity_relations',%s,%s)", (ordinal + position, Jsonb(row)))
            conn.execute('INSERT INTO question_graph_overlay_relations(id,source_row) VALUES(%s,%s)', (row['id'], Jsonb(row)))
        published, pending = [], {}
        for row in docs:
            ident = row['id']
            channel, groups, visible, timeline = _new_source_details(conn, ident, row['source_type'], row['source_id'],
                                                                     row['url'], row['published_at'], row['fetched_at'])
            doc_links = [link for link in links if link['doc_id'] == ident]
            for position, link in enumerate(doc_links):
                conn.execute('INSERT INTO collected_document_entity_order VALUES (%s,%s,%s,%s,%s,0)',
                             (ident, position, link['entity_id'], link['link_type'], link['confidence']))
            doc = reader.get_in_transaction(conn, ident)  # now in the stored entity order
            conn.execute('INSERT INTO collected_document_projection VALUES (%s,%s,%s,%s,%s,%s)',
                         (ident, row['source_type'], row['published_at'], Jsonb(doc.model_dump(mode='json')), visible, groups))
            if visible:  # the slot is set by _place once every document is in
                conn.execute('INSERT INTO collected_document_list_projection VALUES (NULL,%s,%s)',
                             (ident, Jsonb(doc.model_dump(mode='json'))))
                pending[ident] = groups if row['source_type'] == 'blog' else [row['source_type'], *(['people'] if 'people' in groups else [])]
            if timeline:
                key, occurred, millis, label = timeline
                enrichment = next((e['id'] for e in enrichments if e['doc_id'] == ident), None)
                timeline_doc = doc.model_copy(update={'published_at': occurred})
                conn.execute('INSERT INTO collected_timeline_source_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                             (f'source:{ident}', ident, occurred, millis, f"{row['source_type']}:{key}", row['source_type'],
                              sorted({link.name for link in doc.entities}), label,
                              (row['title'] or row['markdown'] or '')[:180], Jsonb(timeline_doc.model_dump(mode='json'))))
                conn.execute('INSERT INTO collected_timeline_source_metadata VALUES (%s,%s,%s)',
                             (ident, enrichment, Jsonb([{'entity_id': l['entity_id'], 'link_type': l['link_type'],
                                                        'confidence': l['confidence']} for l in doc_links])))
            published.append({'id': ident, 'visible': visible, 'timeline': bool(timeline), 'groups': groups,
                              'links': len(doc_links)})
            first = row is docs[0]  # graph additions are recorded once, with the oldest document
            conn.execute('INSERT INTO collected_publications VALUES (%s,%s,%s,%s,%s,%s,%s)',
                         (ident, None,
                          [e['id'] for e in enrichments if e['doc_id'] == ident], [l['id'] for l in doc_links],
                          [e['id'] for e in entities] if first else [], [k['id'] for k in keywords] if first else [],
                          [r['id'] for r in relations] if first else []))
        if not docs:  # graph-only additions: kept under a negative key so `withdraw` can remove them too
            key = conn.execute('SELECT LEAST(COALESCE(min(document_id),0),0)-1 FROM collected_publications').fetchone()[0]
            conn.execute("INSERT INTO collected_publications VALUES (%s,NULL,'{}','{}',%s,%s,%s)",
                         (key, [e['id'] for e in entities], [k['id'] for k in keywords], [r['id'] for r in relations]))
        if pending:
            _place(conn, pending)
        return published


def withdraw(conn, document_id):
    """Remove one published collected document and the graph rows recorded with it."""
    _guard(conn)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
        row = conn.execute('SELECT list_ordinal,enrichment_ids,link_ids,entity_ids,keyword_ids,relation_ids '
                           'FROM collected_publications WHERE document_id=%s FOR UPDATE', (document_id,)).fetchone()
        if row is None:
            raise LookupError('Not a collected document')
        ordinal, enrichments, links, entities, keywords, relations = row
        conn.execute("DELETE FROM video_digest_overlay_rows WHERE table_name='raw_documents' AND row_ordinal=%s", (-document_id,))
        for table, ids, offset in (('enrichments', enrichments, 1_000_000_000), ('entity_links', links, 1_000_000_000),
                                   ('entities', entities, 0), ('entity_keywords', keywords, 0)):
            conn.execute('DELETE FROM video_digest_overlay_rows WHERE table_name=%s AND row_ordinal=ANY(%s)',
                         (table, [-offset - ident for ident in ids]))
        conn.execute("DELETE FROM question_graph_overlay_rows WHERE table_name='entity_relations' "
                     "AND (row_data->>'id')::bigint=ANY(%s)", (relations,))
        conn.execute('DELETE FROM question_graph_overlay_relations WHERE id=ANY(%s)', (relations,))
        if ordinal is not None:
            conn.execute('DELETE FROM collected_document_filter_order WHERE list_ordinal=%s', (ordinal,))
        conn.execute('DELETE FROM collected_document_list_projection WHERE document_id=%s', (document_id,))
        for table in ('document_projection',):
            conn.execute(f'DELETE FROM collected_{table} WHERE id=%s', (document_id,))
        for table in ('timeline_source_projection', 'timeline_source_metadata', 'document_entity_order'):
            conn.execute(f'DELETE FROM collected_{table} WHERE document_id=%s', (document_id,))
        if conn.execute("SELECT to_regclass('document_embedding_overrides')").fetchone()[0] is not None:
            conn.execute('DELETE FROM document_embedding_overrides WHERE document_id=%s', (document_id,))
        conn.execute('DELETE FROM collected_publications WHERE document_id=%s', (document_id,))

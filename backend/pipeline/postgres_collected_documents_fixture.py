"""Publish newly collected documents into the single-path candidate, in place.

Interim collector path (not the target design). An unchanged legacy collector
runs on a writable copy of the candidate's projection file, so it already sees
published videos, overlay entities and the owner's records. Afterwards only the
documents whose id is above the copy's starting high-water mark are published
here, with the same feed, timeline and detail rules as the note overlay
publisher (`postgres_note_overlay_fixture`). Rows live in `collected_*` tables
unioned into the snapshot views; the base generation is never changed.
Only documents newer than every listed document are accepted (they take the
next lower list ordinal); out-of-order backfill fails closed.
"""
from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import GRAPH_LOCK, _guard

VIEWS = ('document_projection', 'document_list_projection', 'document_filter_order', 'timeline_source_projection',
         'timeline_source_metadata', 'document_entity_order')


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


def _rows(work, table, where, params):
    columns = [row[1] for row in work.execute(f'PRAGMA table_info("{table}")')]
    return [dict(zip(columns, row)) for row in work.execute(f'SELECT * FROM "{table}" WHERE {where}', params)]


def publish(conn, work, *, document_floor, entity_floor, keyword_floor, relation_floor):
    """Publish the work copy's documents above the starting high-water marks in one transaction."""
    from pipeline.postgres_note_overlay_fixture import _new_source_details
    from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
    _guard(conn)
    docs = sorted(_rows(work, 'raw_documents', 'id > ?', (document_floor,)), key=lambda row: (row['published_at'] or '', row['id']))
    if not docs:
        return []
    ids = [row['id'] for row in docs]
    marks = ','.join('?' * len(ids))
    enrichments = _rows(work, 'enrichments', f'doc_id IN ({marks})', ids)
    links = _rows(work, 'entity_links', f'doc_id IN ({marks}) ORDER BY id', ids)
    entities = _rows(work, 'entities', 'id > ?', (entity_floor,))
    keywords = _rows(work, 'entity_keywords', 'id > ?', (keyword_floor,))
    relations = _rows(work, 'entity_relations', 'id > ?', (relation_floor,))
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
        newest = conn.execute('SELECT max(published_at) FROM document_projection d JOIN document_list_projection l '
                              'ON l.document_id=d.id').fetchone()[0]
        if any((row['published_at'] or '') < (newest or '') for row in docs):
            raise ValueError('Only documents newer than the current feed can be added in place')
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
        published = []
        for row in docs:  # oldest first, so the newest ends with the lowest ordinal
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
            if visible:
                ordinal = conn.execute('SELECT min(ordinal)-1 FROM document_list_projection').fetchone()[0]
                conn.execute('INSERT INTO collected_document_list_projection VALUES (%s,%s,%s)',
                             (ordinal, ident, Jsonb(doc.model_dump(mode='json'))))
                keys = groups if row['source_type'] == 'blog' else [row['source_type'], *(['people'] if 'people' in groups else [])]
                for key in keys:
                    position = conn.execute('SELECT COALESCE(min(position),0)-1 FROM document_filter_order WHERE filter_key=%s',
                                            (key,)).fetchone()[0]
                    conn.execute('INSERT INTO collected_document_filter_order VALUES (%s,%s,%s)', (key, position, ordinal))
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
                         (ident, ordinal if visible else None,
                          [e['id'] for e in enrichments if e['doc_id'] == ident], [l['id'] for l in doc_links],
                          [e['id'] for e in entities] if first else [], [k['id'] for k in keywords] if first else [],
                          [r['id'] for r in relations] if first else []))
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

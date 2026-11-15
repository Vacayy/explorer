"""Experimental SQLite snapshot → isolated PostgreSQL read model.

The source connection must already be a read-only, consistent transaction. No
LLM, network fetch, file copying, production routing, or incremental sync runs.
"""
import json
from datetime import datetime

from models.spine import EntityTag, FeedDocument
from pipeline.document_read import _read_sqlite_document


def _list_rows(conn):
    from pipeline.visibility import feed_mute_sql
    from routers.spine_feed import resolve_channels

    mute_sql, params = feed_mute_sql(conn)
    rows = list(conn.execute(f'''
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
               rd.markdown, rd.media_json, en.summary, en.model AS enrich_model
        FROM raw_documents rd LEFT JOIN enrichments en ON en.doc_id=rd.id
        WHERE {mute_sql} ORDER BY rd.published_at DESC
    ''', params))
    ids = list(dict.fromkeys(row['id'] for row in rows))
    tags = {doc_id: [] for doc_id in ids}
    # SQLite has a finite parameter limit; bound each lookup independently.
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ','.join('?' for _ in chunk)
        for tag in conn.execute(f'''
            SELECT el.doc_id, el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
            FROM entity_links el JOIN entities e ON el.entity_id=e.id
            WHERE el.doc_id IN ({marks})
        ''', chunk):
            tags[tag['doc_id']].append(EntityTag(
                entity_id=tag['entity_id'], type=tag['type'], name=tag['name'],
                aliases=tag['aliases'], link_type=tag['link_type'], confidence=tag['confidence']))
    channels = resolve_channels(conn, rows)
    return [FeedDocument(
        id=row['id'], source_type=row['source_type'], title=row['title'] or '',
        url=row['url'] or '', published_at=row['published_at'] or '',
        summary=row['summary'], channel=(channels.get(row['id']) or {}).get('name'),
        channel_kind=(channels.get(row['id']) or {}).get('kind'),
        channel_key=(channels.get(row['id']) or {}).get('key'), content=row['markdown'],
        images=json.loads(row['media_json']) if row['media_json'] else [],
        enrich_model=row['enrich_model'], entities=tags[row['id']],
    ) for row in rows]


def load_snapshot(source, connection_factory, *, snapshot_at: str) -> dict:
    """Replace the projection atomically from one existing SQLite transaction."""
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('An active query-only SQLite snapshot is required')
    instant = datetime.fromisoformat(snapshot_at.replace('Z', '+00:00'))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('snapshot_at must include timezone')
    source_rows = list(source.execute('SELECT id, published_at FROM raw_documents ORDER BY id'))
    list_items = _list_rows(source)
    visible_ids = {item.id for item in list_items}
    # All replacement operations use one PG transaction; errors leave the
    # previous complete projection and metadata intact.
    with connection_factory() as target:
        target.execute('DELETE FROM document_list_projection')
        target.execute('DELETE FROM document_projection')
        target.execute('DELETE FROM snapshot_metadata')
        for row in source_rows:
            doc = _read_sqlite_document(source, row['id'])
            if doc is None:
                raise RuntimeError('Snapshot document disappeared')
            payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
            target.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb,%s)',
                           (doc.id, doc.source_type, row['published_at'], payload, doc.id in visible_ids))
        for ordinal, item in enumerate(list_items):
            payload = json.dumps(item.model_dump(mode='json'), ensure_ascii=False)
            target.execute('INSERT INTO document_list_projection VALUES (%s,%s,%s::jsonb)',
                           (ordinal, item.id, payload))
        target.execute('INSERT INTO snapshot_metadata VALUES (TRUE,%s,%s,%s)',
                       (snapshot_at, len(source_rows), len(list_items)))
    return {'snapshot_at': snapshot_at, 'documents': len(source_rows), 'list_rows': len(list_items)}

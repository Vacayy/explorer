"""Experimental SQLite snapshot → isolated PostgreSQL read model.

The source connection must already be a read-only, consistent transaction. No
LLM, network fetch, file copying, production routing, or incremental sync runs.
"""
import json
from datetime import datetime
from itertools import islice

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


# Explicit source tables for this first document slice. Other tables are not
# silently claimed as migrated; they require their own contracts and loaders.
LEGACY_TABLES = ('raw_documents', 'enrichments', 'entities', 'entity_links',
                 'telegram_channels', 'blog_sources', 'youtube_channels',
                 'scrap_links', 'follows', 'youtube_digest_jobs')


def _source_groups(source):
    from pipeline.urls import blog_category, norm_domain

    groups = {}
    sources = list(source.execute('SELECT url, platform FROM blog_sources'))
    for category in ('blog', 'news', 'article'):
        conditions, values = [], []
        for row in sources:
            if blog_category(row['url'], row['platform']) != category:
                continue
            if row['platform'] == 'rss':
                conditions.append("rd.url LIKE '%//%' || ? || '%'")
                values.append(norm_domain(row['url']))
            else:
                conditions.append("rd.url LIKE ? || '%'")
                values.append(row['url'])
        if conditions:
            query = "SELECT rd.id FROM raw_documents rd WHERE rd.source_type='blog' AND (" + ' OR '.join(conditions) + ')'
            for row in source.execute(query, values):
                groups.setdefault(row['id'], set()).add(category)
    for row in source.execute("""
        SELECT DISTINCT el.doc_id FROM entity_links el
        JOIN follows f ON f.entity_id=el.entity_id WHERE el.link_type='person'
    """):
        groups.setdefault(row['doc_id'], set()).add('people')
    return groups


def _insert_batches(target, query, records, *, size=500):
    records = iter(records)
    with target.cursor() as cursor:
        while batch := list(islice(records, size)):
            cursor.executemany(query, batch)


def _store_legacy_tables(source, target):
    for name in LEGACY_TABLES:
        schema = source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if schema is None or not schema['sql']:
            raise ValueError(f'Required source table missing: {name}')
        columns = [r['name'] for r in source.execute(f'PRAGMA table_info("{name}")')]
        count = source.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        target.execute('INSERT INTO legacy_snapshot_tables VALUES (%s,%s::jsonb,%s,%s)',
                       (name, json.dumps(columns), schema['sql'], count))
        def records():
            for ordinal, row in enumerate(source.execute(f'SELECT * FROM "{name}"')):
                # Reject unsupported BLOB/non-finite values instead of losing them.
                yield (name, ordinal, json.dumps(dict(row), ensure_ascii=False, allow_nan=False))
        _insert_batches(target, 'INSERT INTO legacy_snapshot_rows VALUES (%s,%s,%s::jsonb)', records())


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
    groups = _source_groups(source)
    # All replacement operations use one PG transaction; errors leave the
    # previous complete projection and metadata intact.
    with connection_factory() as target:
        target.execute('DELETE FROM legacy_snapshot_rows')
        target.execute('DELETE FROM legacy_snapshot_tables')
        target.execute('DELETE FROM document_list_projection')
        target.execute('DELETE FROM document_projection')
        target.execute('DELETE FROM snapshot_metadata')
        _store_legacy_tables(source, target)
        def documents():
            for row in source_rows:
                doc = _read_sqlite_document(source, row['id'])
                if doc is None:
                    raise RuntimeError('Snapshot document disappeared')
                payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
                yield (doc.id, doc.source_type, row['published_at'], payload,
                       doc.id in visible_ids, sorted(groups.get(doc.id, ())))
        _insert_batches(target, 'INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb,%s,%s)',
                        documents())
        def feed_rows():
            for ordinal, item in enumerate(list_items):
                payload = json.dumps(item.model_dump(mode='json'), ensure_ascii=False)
                yield (ordinal, item.id, payload)
        _insert_batches(target, 'INSERT INTO document_list_projection VALUES (%s,%s,%s::jsonb)',
                        feed_rows())
        target.execute('INSERT INTO snapshot_metadata VALUES (TRUE,%s,%s,%s)',
                       (snapshot_at, len(source_rows), len(list_items)))
    return {'snapshot_at': snapshot_at, 'documents': len(source_rows), 'list_rows': len(list_items)}

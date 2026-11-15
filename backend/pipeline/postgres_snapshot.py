"""Experimental SQLite snapshot → isolated PostgreSQL read model.

The source connection must already be a read-only, consistent transaction. No
LLM, network fetch, file copying, production routing, or incremental sync runs.
"""
import json
from datetime import datetime, timezone
from itertools import islice
from collections import defaultdict, deque

from models.spine import EntityTag, FeedDocument
from pipeline.document_read import _read_sqlite_documents

# Stable transaction lock; serializes all loaders in this PostgreSQL database.
SNAPSHOT_LOCK_KEY = 0x4558504C4F524552


def _visible_ids(conn):
    from pipeline.visibility import feed_mute_sql
    mute_sql, params = feed_mute_sql(conn)
    return {row['id'] for row in conn.execute(f'SELECT rd.id FROM raw_documents rd WHERE {mute_sql}', params)}


def _list_rows(conn, *, batch_size=250):
    """Produce the existing SQLite feed in bounded batches, in source order."""
    from pipeline.visibility import feed_mute_sql
    from routers.spine_feed import resolve_channels

    mute_sql, params = feed_mute_sql(conn)
    cursor = conn.execute(f"""
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
               rd.markdown, rd.media_json, en.summary, en.model AS enrich_model
        FROM raw_documents rd LEFT JOIN enrichments en ON en.doc_id=rd.id
        WHERE {mute_sql} ORDER BY rd.published_at DESC
    """, params)
    while rows := cursor.fetchmany(batch_size):
        ids = list(dict.fromkeys(row['id'] for row in rows))
        tags = {doc_id: [] for doc_id in ids}
        marks = ','.join('?' for _ in ids)
        for tag in conn.execute(f"""
            SELECT el.doc_id, el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
            FROM entity_links el JOIN entities e ON el.entity_id=e.id
            WHERE el.doc_id IN ({marks})
        """, ids):
            tags[tag['doc_id']].append(EntityTag(
                entity_id=tag['entity_id'], type=tag['type'], name=tag['name'],
                aliases=tag['aliases'], link_type=tag['link_type'], confidence=tag['confidence']))
        channels = resolve_channels(conn, rows)
        for row in rows:
            yield FeedDocument(
                id=row['id'], source_type=row['source_type'], title=row['title'] or '',
                url=row['url'] or '', published_at=row['published_at'] or '',
                summary=row['summary'], channel=(channels.get(row['id']) or {}).get('name'),
                channel_kind=(channels.get(row['id']) or {}).get('kind'),
                channel_key=(channels.get(row['id']) or {}).get('key'), content=row['markdown'],
                images=json.loads(row['media_json']) if row['media_json'] else [],
                enrich_model=row['enrich_model'], entities=tags[row['id']],
            )


# Explicit source tables for this first document slice. Other tables are not
# silently claimed as migrated; they require their own contracts and loaders.
LEGACY_TABLES = ('raw_documents', 'enrichments', 'entities', 'entity_links',
                 'telegram_channels', 'blog_sources', 'youtube_channels',
                 'scrap_links', 'follows', 'youtube_digest_jobs',
                 'entity_digests', 'source_digests', 'transcripts', 'transcript_follow',
                 'trade_stats', 'trade_follow', 'narratives', 'reports', 'scenarios',
                 'channel_reads')


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


def _filter_predicate(source, name):
    if name in {'blog', 'news', 'article'}:
        from pipeline.urls import blog_category, norm_domain
        conditions, values = [], []
        for row in source.execute('SELECT url, platform FROM blog_sources'):
            if blog_category(row['url'], row['platform']) != name:
                continue
            if row['platform'] == 'rss':
                conditions.append("rd.url LIKE '%//%' || ? || '%'")
                values.append(norm_domain(row['url']))
            else:
                conditions.append("rd.url LIKE ? || '%'")
                values.append(row['url'])
        if not conditions:
            return None, []
        return "rd.source_type = 'blog' AND (" + ' OR '.join(conditions) + ')', values
    if name == 'people':
        return """rd.id IN (SELECT el.doc_id FROM entity_links el
                 JOIN follows f ON f.entity_id=el.entity_id WHERE el.link_type='person')""", []
    return 'rd.source_type = ?', [name]


def _filter_orders(source, ordinal_keys):
    from pipeline.visibility import feed_mute_sql
    names = {row['source_type'] for row in source.execute('SELECT DISTINCT source_type FROM raw_documents')}
    names.update({'blog', 'news', 'article', 'people'})
    mute_sql, mute_params = feed_mute_sql(source)
    for name in sorted(names):
        predicate, params = _filter_predicate(source, name)
        if predicate is None:
            continue
        available = {key: deque(values) for key, values in ordinal_keys.items()}
        query = f"""SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
                    rd.markdown, rd.media_json, en.summary, en.model AS enrich_model
                    FROM raw_documents rd LEFT JOIN enrichments en ON en.doc_id=rd.id
                    WHERE {mute_sql} AND {predicate} ORDER BY rd.published_at DESC"""
        for position, row in enumerate(source.execute(query, [*mute_params, *params])):
            key = (row['id'], row['summary'], row['enrich_model'])
            if key not in available or not available[key]:
                raise RuntimeError('Filtered feed row missing from full feed projection')
            yield (name, position, available[key].popleft())


def _timeline_source_rows(source, *, batch_size=250):
    """Capture existing source-lane responses in the same SQLite snapshot."""
    from pipeline.timeline import _projection, _documents, utc

    query, params = _projection(source, scope='sources')
    cursor = source.execute(query, params)
    while rows := cursor.fetchmany(batch_size):
        ids = [row['ref'] for row in rows]
        documents = _documents(source, ids)
        marks = ','.join('?' for _ in ids)
        topics = defaultdict(set)
        for tag in source.execute(f"SELECT el.doc_id,e.name FROM entity_links el JOIN entities e ON e.id=el.entity_id WHERE el.doc_id IN ({marks})", ids):
            topics[tag['doc_id']].add(tag['name'])
        published = {r['id']: r['published_at'] for r in source.execute(
            f'SELECT id,published_at FROM raw_documents WHERE id IN ({marks})', ids)}
        for row in rows:
            doc = documents[row['ref']]
            yield (row['id'], row['ref'], utc(row['ts']), row['channel'], row['platform'],
                   sorted(topics[row['ref']]), '게시' if published[row['ref']] else '수집',
                   json.dumps(doc.model_dump(mode='json'), ensure_ascii=False))


def _timeline_system_rows(source):
    """Capture existing system-lane items without calling a generator or LLM."""
    from pipeline.timeline import _projection, timeline
    query, params = _projection(source, scope='system')
    metadata = {r['id']: r for r in source.execute(query, params) if r['ts']}
    page = 1
    while True:
        result = timeline(source, scope='system', size=250, page=page,
                          until='9999-12-31T23:59:59+00:00')
        for item in result.items:
            row = metadata[item.id]
            yield (item.id, item.occurred_at, row['channel'], row['topic'], row['preview'] or '',
                   json.dumps(item.model_dump(mode='json'), ensure_ascii=False))
        if not result.has_more:
            break
        page += 1


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
    # The caller-supplied snapshot_at is a label, not proof of capture time.
    # All replacement operations share one transaction and writer lock.
    with connection_factory() as target:
        database, schema = target.execute('SELECT current_database(), current_schema()').fetchone()
        if database != 'fixture' or not schema or not schema.startswith('refactor_fixture_'):
            raise ValueError('Refusing snapshot writes outside the disposable fixture schema')
        target.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        prior = target.execute('SELECT snapshot_at FROM snapshot_metadata WHERE singleton').fetchone()
        if prior:
            previous = datetime.fromisoformat(prior[0].replace('Z', '+00:00'))
            if instant < previous:
                raise ValueError('Older snapshot cannot replace a newer snapshot')
        # The first data read establishes a deferred SQLite snapshot if the
        # caller has not already read. This is an observation, not a guarantee
        # of the source backup time or an exact snapshot acquisition time.
        source_rows = list(source.execute('SELECT id, published_at FROM raw_documents ORDER BY id'))
        source_observed_at = datetime.now(timezone.utc)
        visible_ids = _visible_ids(source)
        groups = _source_groups(source)
        target.execute('DELETE FROM legacy_snapshot_rows')
        target.execute('DELETE FROM legacy_snapshot_tables')
        target.execute('DELETE FROM timeline_system_projection')
        target.execute('DELETE FROM timeline_source_projection')
        target.execute('DELETE FROM document_filter_order')
        target.execute('DELETE FROM document_entity_order')
        target.execute('DELETE FROM document_list_projection')
        target.execute('DELETE FROM document_projection')
        target.execute('DELETE FROM snapshot_metadata')
        _store_legacy_tables(source, target)
        entity_orders = []
        def documents():
            ids = (row['id'] for row in source_rows)
            for row, doc in zip(source_rows, _read_sqlite_documents(source, ids), strict=True):
                if doc is None or doc.id != row['id']:
                    raise RuntimeError('Snapshot document disappeared')
                counts = defaultdict(int)
                for position, tag in enumerate(doc.entities):
                    key = (tag.entity_id, tag.link_type, tag.confidence)
                    entity_orders.append((doc.id, position, *key, counts[key]))
                    counts[key] += 1
                payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
                yield (doc.id, doc.source_type, row['published_at'], payload,
                       doc.id in visible_ids, sorted(groups.get(doc.id, ())))
        _insert_batches(target, 'INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb,%s,%s)',
                        documents())
        _insert_batches(target, 'INSERT INTO document_entity_order VALUES (%s,%s,%s,%s,%s,%s)',
                        entity_orders)
        list_count = 0
        ordinal_keys = defaultdict(list)
        def feed_rows():
            nonlocal list_count
            for ordinal, item in enumerate(_list_rows(source)):
                list_count += 1
                payload = json.dumps(item.model_dump(mode='json'), ensure_ascii=False)
                ordinal_keys[(item.id, item.summary, item.enrich_model)].append(ordinal)
                yield (ordinal, item.id, payload)
        _insert_batches(target, 'INSERT INTO document_list_projection VALUES (%s,%s,%s::jsonb)',
                        feed_rows())
        _insert_batches(target, 'INSERT INTO document_filter_order VALUES (%s,%s,%s)',
                        _filter_orders(source, ordinal_keys))
        _insert_batches(target, 'INSERT INTO timeline_source_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)',
                        _timeline_source_rows(source))
        _insert_batches(target, 'INSERT INTO timeline_system_projection VALUES (%s,%s,%s,%s,%s,%s::jsonb)',
                        _timeline_system_rows(source))
        target.execute('INSERT INTO snapshot_metadata '
                       '(singleton,snapshot_at,source_observed_at,document_count,list_row_count) '
                       'VALUES (TRUE,%s,%s,%s,%s)',
                       (snapshot_at, source_observed_at, len(source_rows), list_count))
    return {'snapshot_at': snapshot_at, 'documents': len(source_rows), 'list_rows': list_count}

"""Rebuild the experimental source timeline from archived PostgreSQL rows."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import json

from models.spine import EntityTag, FeedDocument
from pipeline.postgres_snapshot import SNAPSHOT_LOCK_KEY, _insert_batches
from pipeline.sources import source_names_from_rows
from pipeline.timeline import utc
from pipeline.urls import url_belongs


def rebuild_source_timeline(connection_factory):
    """Replace only source-lane projection, using archived rows and join metadata."""
    with connection_factory() as conn:
        database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
        if database != 'fixture' or not schema or not schema.startswith('refactor_fixture_'):
            raise ValueError('Refusing rebuild outside disposable fixture schema')
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        tables = defaultdict(list)
        for table, row in conn.execute("SELECT table_name,row_data FROM legacy_snapshot_rows WHERE table_name IN ('entities','telegram_channels','blog_sources','youtube_channels') ORDER BY table_name,row_ordinal"):
            tables[table].append(row)
        metadata = {row[0]: (row[1], row[2]) for row in conn.execute('SELECT document_id,enrichment_id,entity_order FROM timeline_source_metadata')}
        entities = {row['id']: row for row in tables['entities']}
        tg_rows, yt_rows, blogs = tables['telegram_channels'], tables['youtube_channels'], tables['blog_sources']
        tg = {r['channel_name']: r['display_name'] or r['channel_name'] for r in tg_rows}
        yt = {r['channel_id']: r['title'] for r in yt_rows}
        active_tg = {r['channel_name'] for r in tg_rows if r['is_active'] == 1}
        active_yt = {r['channel_id'] for r in yt_rows if r['is_active'] == 1}
        blog_names = [(r['url'], r['blog_name'] or r['url']) for r in blogs]
        blog_names.sort(key=lambda pair: (pair[0] is not None, len(pair[0] or '')), reverse=True)
        scraps = {}
        seen = set()
        def records():
            with conn.cursor(name='timeline_raw_document_scan') as cursor:
                cursor.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal")
                while batch := cursor.fetchmany(200):
                    docs = [item[0] for item in batch]
                    ids = [str(doc['id']) for doc in docs]
                    enrichments = {r[0]['id']: r[0] for r in conn.execute(
                        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='enrichments' AND row_data->>'doc_id'=ANY(%s)", (ids,))}
                    links = defaultdict(list)
                    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=ANY(%s) ORDER BY row_ordinal", (ids,)):
                        if row['entity_id'] in entities:
                            links[row['doc_id']].append(row)
                    for doc in docs:
                        kind, sid, url = doc['source_type'], doc['source_id'] or '', doc['url'] or ''
                        key = sid.split('/', 1)[0] if '/' in sid else ''
                        if kind == 'telegram':
                            visible = key in active_tg
                        elif kind == 'youtube':
                            visible = key in active_yt
                        elif kind == 'blog':
                            visible = (any(r['is_active'] == 1 and url_belongs(url, r['url']) for r in blogs) and
                                       not any(r['is_active'] == 0 and url_belongs(url, r['url']) for r in blogs))
                            key = next((prefix for prefix_only in (True, False) for prefix, _ in blog_names
                                        if url_belongs(url, prefix, prefix_only=prefix_only)), '')
                        else:
                            visible = kind == 'memo'
                        if not visible:
                            continue
                        stamp = doc['published_at'] or doc['fetched_at']
                        try:
                            occurred = utc(stamp)
                            instant = datetime.fromisoformat(occurred)
                        except (TypeError, ValueError, AttributeError):
                            continue
                        if doc['id'] not in metadata:
                            raise ValueError('Missing source timeline join metadata')
                        enrichment_id, order = metadata[doc['id']]
                        enrichment = enrichments.get(enrichment_id) if enrichment_id is not None else None
                        if enrichment_id is not None and (enrichment is None or enrichment['doc_id'] != doc['id']):
                            raise ValueError('Missing source timeline enrichment')
                        available = defaultdict(deque)
                        for link in links[doc['id']]:
                            available[(link['entity_id'], link['link_type'], link['confidence'])].append(link)
                        tags = []
                        for entry in order:
                            tag_key = (entry['entity_id'], entry['link_type'], entry['confidence'])
                            if not available[tag_key]:
                                raise ValueError('Missing source timeline entity')
                            link = available[tag_key].popleft()
                            entity = entities[link['entity_id']]
                            tags.append(EntityTag(entity_id=link['entity_id'], type=entity['type'], name=entity['name'],
                                                  aliases=entity['aliases'], link_type=link['link_type'], confidence=link['confidence']))
                        if any(available.values()):
                            raise ValueError('Source timeline entity metadata incomplete')
                        name = source_names_from_rows([doc], telegram=tg, blogs=blog_names, youtube=yt, scraps=scraps).get(doc['id']) or {}
                        try:
                            images = json.loads(doc['media_json'] or '[]')
                            images = [x for x in images if isinstance(x, str)] if isinstance(images, list) else []
                        except (ValueError, TypeError):
                            images = []
                        item = FeedDocument(id=doc['id'], source_type=kind, title=doc['title'] or '', url=url,
                                            published_at=occurred, summary=enrichment['summary'] if enrichment else None,
                                            channel=name.get('name'), channel_kind=name.get('kind'), channel_key=name.get('key'),
                                            content=doc['markdown'], images=images,
                                            enrich_model=enrichment['model'] if enrichment else None, entities=tags)
                        delta = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
                        micros = (delta.days*86400 + delta.seconds)*1000000 + delta.microseconds
                        millis = (micros + 500)//1000
                        preview = (doc['title'] or doc['markdown'] or '')[:180]
                        seen.add(doc['id'])
                        yield (f"source:{doc['id']}", doc['id'], occurred, millis, f'{kind}:{key}', kind,
                                     sorted({e.name for e in tags}), '게시' if doc['published_at'] else '수집', preview,
                                     json.dumps(item.model_dump(mode='json'), ensure_ascii=False))

        conn.execute('DELETE FROM timeline_source_projection')
        _insert_batches(conn, 'INSERT INTO timeline_source_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)', records())
        if seen != set(metadata):
            raise ValueError('Source timeline join metadata does not match source documents')
        return len(seen)

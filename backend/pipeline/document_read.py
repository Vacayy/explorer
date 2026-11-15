"""Document read boundary shared by the existing API and isolated adapters."""
import json
from typing import Protocol

from models.spine import EntityTag, FeedDocument


class DocumentReader(Protocol):
    def get(self, doc_id: int) -> FeedDocument | None: ...


class SQLiteDocumentReader:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def get(self, doc_id: int) -> FeedDocument | None:
        conn = self.connection_factory()
        try:
            return _read_sqlite_document(conn, doc_id)
        finally:
            conn.close()


def _read_sqlite_document(conn, doc_id: int) -> FeedDocument | None:
    r = conn.execute("""
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
               rd.markdown, rd.raw_content, rd.digest_status, rd.media_json,
               en.summary, en.model AS enrich_model
        FROM raw_documents rd
        LEFT JOIN enrichments en ON en.id = (SELECT id FROM enrichments WHERE doc_id=rd.id ORDER BY enriched_at DESC, id DESC LIMIT 1)
        WHERE rd.id = ?
    """, (doc_id,)).fetchone()
    if not r:
        return None

    from pipeline.youtube_digest import fields
    video_fields = fields(conn, r)

    tags = [EntityTag(
        entity_id=t["entity_id"], type=t["type"], name=t["name"],
        aliases=t["aliases"], link_type=t["link_type"], confidence=t["confidence"],
    ) for t in conn.execute("""
        SELECT el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
        FROM entity_links el JOIN entities e ON el.entity_id = e.id
        WHERE el.doc_id = ?""", (doc_id,))]
    from routers.spine_feed import resolve_channels
    channel = resolve_channels(conn, [r]).get(r["id"]) or {}

    return _document(r, tags, channel, video_fields)


def _document(row, tags, channel, video_fields):
    return FeedDocument(
        id=row['id'], source_type=row['source_type'], title=row['title'] or '',
        url=row['url'] or '', published_at=row['published_at'] or '',
        summary=row['summary'], channel=channel.get('name'),
        channel_kind=channel.get('kind'), channel_key=channel.get('key'),
        content=row['markdown'] or row['raw_content'], **video_fields,
        images=json.loads(row['media_json']) if row['media_json'] else [],
        enrich_model=row['enrich_model'], entities=tags,
    )


def _read_sqlite_documents(conn, doc_ids, *, batch_size: int = 250):
    """Yield original detail responses in input order, including missing IDs."""
    from itertools import islice
    from pipeline.youtube_digest import fields
    from routers.spine_feed import resolve_channels

    if not 1 <= batch_size <= 500:
        raise ValueError('batch_size must be between 1 and 500')
    ids = iter(doc_ids)
    while chunk := list(islice(ids, batch_size)):
        unique = list(dict.fromkeys(chunk))
        marks = ','.join('?' for _ in unique)
        rows = list(conn.execute(f'''
            SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
                   rd.markdown, rd.raw_content, rd.digest_status, rd.media_json,
                   en.summary, en.model AS enrich_model
            FROM raw_documents rd
            LEFT JOIN enrichments en ON en.id = (
                SELECT id FROM enrichments WHERE doc_id=rd.id ORDER BY enriched_at DESC, id DESC LIMIT 1
            ) WHERE rd.id IN ({marks})
        ''', unique))
        by_id = {row['id']: row for row in rows}
        tags = {row['id']: [] for row in rows}
        for t in conn.execute(f'''
            SELECT el.doc_id, el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
            FROM entity_links el JOIN entities e ON el.entity_id=e.id
            WHERE el.doc_id IN ({marks})
        ''', unique):
            if t['doc_id'] in tags:
                tags[t['doc_id']].append(EntityTag(
                    entity_id=t['entity_id'], type=t['type'], name=t['name'],
                    aliases=t['aliases'], link_type=t['link_type'], confidence=t['confidence']))
        channels = resolve_channels(conn, rows) if rows else {}
        for doc_id in chunk:
            row = by_id.get(doc_id)
            if row is None:
                yield None
                continue
            channel = channels.get(doc_id) or {}
            yield _document(row, tags[doc_id], channel, fields(conn, row))

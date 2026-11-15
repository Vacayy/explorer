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

    content = r["markdown"] or r["raw_content"]
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

    return FeedDocument(
        id=r["id"], source_type=r["source_type"], title=r["title"] or "",
        url=r["url"] or "", published_at=r["published_at"] or "",
        summary=r["summary"], channel=channel.get("name"),
        channel_kind=channel.get("kind"), channel_key=channel.get("key"),
        content=content, **video_fields,
        images=json.loads(r["media_json"]) if r["media_json"] else [],
        enrich_model=r["enrich_model"], entities=tags,
    )

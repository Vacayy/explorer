"""문서 디테일 API — 수집한 raw content를 내부 페이지에서 열람 (외부 이동 대신)."""
import json

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException
from database import get_connection
from models.spine import EntityTag, FeedDocument

router = APIRouter(prefix="/api/spine/doc", tags=["spine"])


class RelatedDoc(BaseModel):
    id: int
    source_type: str
    title: str | None
    published_at: str | None


@router.get("/{doc_id}/related", response_model=list[RelatedDoc])
def get_related(doc_id: int):
    """임베딩 유사 문서 5건 — 아카이브 재방문 촉진 (H2)."""
    from pipeline.search import related_docs
    return [RelatedDoc(**d) for d in related_docs(doc_id)]


@router.get("/{doc_id}", response_model=FeedDocument)
def get_document(doc_id: int):
    conn = get_connection()
    r = conn.execute("""
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
               rd.markdown, rd.raw_content, rd.digest_status, rd.media_json,
               en.summary, en.model AS enrich_model
        FROM raw_documents rd
        LEFT JOIN enrichments en ON en.doc_id = rd.id
        WHERE rd.id = ?
    """, (doc_id,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "문서를 찾을 수 없습니다")

    content = r["markdown"]
    if r["source_type"] == "youtube" and r["digest_status"] != "ok":
        transcript = r["raw_content"] or ""
        if len(transcript) >= 100:
            from pipeline.connectors.youtube import digest_transcript, _digest_body
            digest = digest_transcript(r["title"] or "", transcript)
            body = _digest_body(digest, transcript) if digest else transcript
            conn.execute(
                "UPDATE raw_documents SET raw_content=?, markdown=?, digest_status=? WHERE id=?",
                (body, body, "ok" if digest else "failed", doc_id))
            conn.commit()
            content = body

    tags = [EntityTag(
        entity_id=t["entity_id"], type=t["type"], name=t["name"],
        aliases=t["aliases"], link_type=t["link_type"], confidence=t["confidence"],
    ) for t in conn.execute("""
        SELECT el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
        FROM entity_links el JOIN entities e ON el.entity_id = e.id
        WHERE el.doc_id = ?""", (doc_id,))]
    from routers.spine_feed import resolve_channels
    channel = resolve_channels(conn, [r]).get(r["id"]) or {}
    conn.close()

    return FeedDocument(
        id=r["id"], source_type=r["source_type"], title=r["title"] or "",
        url=r["url"] or "", published_at=r["published_at"] or "",
        summary=r["summary"], channel=channel.get("name"),
        channel_kind=channel.get("kind"), channel_key=channel.get("key"),
        content=content,
        images=json.loads(r["media_json"]) if r["media_json"] else [],
        enrich_model=r["enrich_model"], entities=tags,
    )

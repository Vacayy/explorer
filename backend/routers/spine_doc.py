"""문서 디테일 API — 수집한 raw content를 내부 페이지에서 열람 (외부 이동 대신)."""
import json

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, BackgroundTasks
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
        LEFT JOIN enrichments en ON en.id = (SELECT id FROM enrichments WHERE doc_id=rd.id ORDER BY enriched_at DESC, id DESC LIMIT 1)
        WHERE rd.id = ?
    """, (doc_id,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "문서를 찾을 수 없습니다")

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
    conn.close()

    return FeedDocument(
        id=r["id"], source_type=r["source_type"], title=r["title"] or "",
        url=r["url"] or "", published_at=r["published_at"] or "",
        summary=r["summary"], channel=channel.get("name"),
        channel_kind=channel.get("kind"), channel_key=channel.get("key"),
        content=content, **video_fields,
        images=json.loads(r["media_json"]) if r["media_json"] else [],
        enrich_model=r["enrich_model"], entities=tags,
    )


@router.post("/{doc_id}/digest", status_code=202)
def generate_digest(doc_id: int, background_tasks: BackgroundTasks):
    from pipeline.youtube_digest import queue, execute
    job = queue(doc_id)
    if job['token']:
        background_tasks.add_task(execute, doc_id, job['token'])
    return {'status': job['status']}

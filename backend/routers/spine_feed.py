"""통합 피드 API — raw_documents 기반 (greenfield spine 읽기)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from database import get_connection
from models.spine import EntityTag, FeedDocument, FeedResponse

router = APIRouter(prefix="/api/spine/feed", tags=["spine"])


@router.get("", response_model=FeedResponse)
def get_feed(
    q: str | None = Query(None, description="하이브리드 검색어 (BM25+벡터 RRF)"),
    source: str | None = Query(None, description="blog | telegram | note"),
    stock: str | None = Query(None, description="종목코드 (entities.aliases)"),
    industry: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    conn = get_connection()
    where, params = ["1=1"], []

    # 검색어: 하이브리드 검색으로 랭킹된 doc_id 집합을 필터 + 정렬 기준으로 사용
    rank_order: list[int] = []
    if q and q.strip():
        from pipeline.search import search as hybrid_search
        rank_order = [r["doc_id"] for r in hybrid_search(q.strip(), k=100)]
        if not rank_order:
            conn.close()
            return FeedResponse(items=[], total=0, page=page, size=size,
                                as_of=datetime.now(timezone.utc).isoformat())
        ph = ",".join("?" for _ in rank_order)
        where.append(f"rd.id IN ({ph})")
        params.extend(rank_order)

    if source:
        where.append("rd.source_type = ?")
        params.append(source)

    # 엔티티 필터: link 존재 조건 (stock=종목코드→aliases, industry/topic=이름)
    for link_type, ent_field, value in (
        ("stock", "aliases", stock),
        ("industry", "name", industry),
        ("topic", "name", topic),
    ):
        if value:
            where.append(f"""rd.id IN (
                SELECT el.doc_id FROM entity_links el JOIN entities e ON el.entity_id = e.id
                WHERE el.link_type = ? AND e.{ent_field} = ?)""")
            params.extend([link_type, value])

    where_sql = " AND ".join(where)
    select_sql = f"""
        SELECT rd.id, rd.source_type, rd.title, rd.url, rd.published_at,
               en.summary, en.model AS enrich_model
        FROM raw_documents rd
        LEFT JOIN enrichments en ON en.doc_id = rd.id
        WHERE {where_sql}
    """

    if rank_order:
        # 검색 모드: 관련도(RRF) 순 정렬 — 파이썬에서 정렬·페이지네이션
        all_rows = conn.execute(select_sql, params).fetchall()
        pos = {doc_id: i for i, doc_id in enumerate(rank_order)}
        all_rows.sort(key=lambda r: pos.get(r["id"], 10**9))
        total = len(all_rows)
        rows = all_rows[(page - 1) * size:(page - 1) * size + size]
    else:
        total = conn.execute(
            f"SELECT count(*) FROM raw_documents rd WHERE {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            select_sql + " ORDER BY rd.published_at DESC LIMIT ? OFFSET ?",
            [*params, size, (page - 1) * size],
        ).fetchall()

    # 엔티티 태그 일괄 조회
    doc_ids = [r["id"] for r in rows]
    tags: dict[int, list[EntityTag]] = {d: [] for d in doc_ids}
    if doc_ids:
        ph = ",".join("?" for _ in doc_ids)
        for t in conn.execute(f"""
            SELECT el.doc_id, el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
            FROM entity_links el JOIN entities e ON el.entity_id = e.id
            WHERE el.doc_id IN ({ph})""", doc_ids):
            tags[t["doc_id"]].append(EntityTag(
                entity_id=t["entity_id"], type=t["type"], name=t["name"],
                aliases=t["aliases"], link_type=t["link_type"], confidence=t["confidence"]))
    conn.close()

    return FeedResponse(
        items=[FeedDocument(
            id=r["id"], source_type=r["source_type"], title=r["title"] or "",
            url=r["url"] or "", published_at=r["published_at"] or "",
            summary=r["summary"], enrich_model=r["enrich_model"],
            entities=tags.get(r["id"], []),
        ) for r in rows],
        total=total, page=page, size=size,
        as_of=datetime.now(timezone.utc).isoformat(),
    )

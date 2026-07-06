"""적재: RawDoc → raw_documents + enrichments + entity_links.

content_hash로 멱등성 보장:
- 동일 문서 & 동일 내용 → skip (enrich 재실행 안 함 → LLM 비용 0)
- 내용 변경 → 갱신 후 이전 enrichment·링크 삭제하고 재enrich (stale 방지)
- keyword 티어 결과는 LLM 사용 가능해지면 자동 재enrich (백필)
"""
import hashlib
import os

from database import get_connection
from pipeline.base import RawDoc
from pipeline.normalize import to_markdown
from pipeline import enrich as enrich_mod


def _hash(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _get_or_create_entity(conn, type_: str, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM entities WHERE type=? AND name=?", (type_, name)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO entities (type, name) VALUES (?, ?)", (type_, name)
    )
    return cur.lastrowid


def _link(conn, doc_id: int, title: str, markdown: str, result: dict):
    text = f"{title}\n{markdown}"
    for name in result.get("industries", []):
        eid = _get_or_create_entity(conn, "sector", name)
        conn.execute(
            "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
            "VALUES (?, ?, 'industry', 0.5)", (doc_id, eid))
    for name in result.get("topics", []):
        eid = _get_or_create_entity(conn, "theme", name)
        conn.execute(
            "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
            "VALUES (?, ?, 'topic', 0.5)", (doc_id, eid))
    # 종목: 기존 company 엔티티 이름이 본문에 등장하면 링크
    for row in conn.execute("SELECT id, name FROM entities WHERE type='company'").fetchall():
        if row["name"] and row["name"] in text:
            conn.execute(
                "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                "VALUES (?, ?, 'stock', 0.6)", (doc_id, row["id"]))


def store_document(doc: RawDoc) -> dict:
    md = to_markdown(doc)
    h = _hash(md)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, content_hash FROM raw_documents WHERE source_type=? AND source_id=?",
        (doc.source_type, doc.source_id),
    ).fetchone()

    if existing and existing["content_hash"] == h:
        # 내용 동일 — 문서는 그대로 두되, enrich 체크는 계속 진행
        # (keyword→LLM 백필이 여기서 일어난다)
        doc_id, status = existing["id"], "unchanged"
    elif existing:
        conn.execute(
            "UPDATE raw_documents SET title=?, url=?, published_at=?, raw_content=?, "
            "markdown=?, content_hash=?, fetched_at=datetime('now') WHERE id=?",
            (doc.title, doc.url, doc.published_at, doc.raw_content, md, h, existing["id"]),
        )
        doc_id, status = existing["id"], "updated"
    else:
        cur = conn.execute(
            "INSERT INTO raw_documents (source_type, source_id, title, url, published_at, "
            "raw_content, markdown, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.source_type, doc.source_id, doc.title, doc.url, doc.published_at,
             doc.raw_content, md, h),
        )
        doc_id, status = cur.lastrowid, "new"
    conn.commit()

    # enrich 필요 판정:
    # - 현재 내용(hash)에 대한 enrichment가 없거나
    # - keyword 티어 결과인데 LLM이 사용 가능해졌으면 (백필)
    cached = conn.execute(
        "SELECT model FROM enrichments WHERE doc_id=? AND content_hash=?", (doc_id, h)
    ).fetchone()
    llm_ready = bool(os.getenv("ANTHROPIC_API_KEY"))
    needs_enrich = cached is None or (cached["model"] == "keyword" and llm_ready)

    if needs_enrich:
        # 이전 내용/이전 티어의 enrichment·링크를 먼저 제거 → 문서당 정확히 1개 유지, stale 링크 방지
        conn.execute("DELETE FROM enrichments WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM entity_links WHERE doc_id=?", (doc_id,))
        result = enrich_mod.enrich(doc.title, md)
        conn.execute(
            "INSERT INTO enrichments (doc_id, summary, sentiment, model, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc_id, result.get("summary"), result.get("sentiment"),
             result.get("model", "keyword"), h),
        )
        _link(conn, doc_id, doc.title, md, result)
        conn.commit()

    conn.close()
    return {"doc_id": doc_id, "status": status}

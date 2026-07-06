"""적재: RawDoc → raw_documents + enrichments + entity_links.

content_hash로 멱등성 보장:
- 동일 문서 & 동일 내용 → skip (enrich 재실행 안 함 → LLM 비용 0)
- 내용 변경 → 갱신 후 이전 enrichment·링크 삭제하고 재enrich (stale 방지)
- keyword 티어 결과는 LLM 사용 가능해지면 자동 재enrich (백필)
"""
import hashlib
import os
import re

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
    # 종목: 기존 company 엔티티 이름이 본문에 등장하면 링크.
    # 오탐 완화 휴리스틱 (근본 해결은 LLM enrich):
    #  - 모든 이름: 앞이 한글/영숫자면 다른 단어의 꼬리 매칭('하이닉스'의 '이닉스')이므로 제외.
    #    뒤는 조사('삼성전자는')를 허용해야 하므로 ≤2자 이름만 뒤 경계도 요구
    #    ('레이','SK','테스' 등 일반 단어 오탐 — 조사 붙은 언급은 놓치지만 precision 우선)
    #  - 더 긴 매칭명에 포함된 이름('이닉스'⊂'SK하이닉스'): 등장 횟수가
    #    포함하는 이름들의 합계 이하면 전부 내부 매칭으로 보고 제외
    hits = []
    for row in conn.execute("SELECT id, name FROM entities WHERE type='company'").fetchall():
        name = row["name"]
        if not name or name not in text:
            continue
        pat = rf"(?<![0-9A-Za-z가-힣]){re.escape(name)}"
        if len(name) <= 2:
            pat += r"(?![0-9A-Za-z가-힣])"
        if not re.search(pat, text):
            continue
        hits.append((row["id"], name))
    matched_names = [n for _, n in hits]
    for eid, name in hits:
        longer = [o for o in matched_names if o != name and name in o]
        if longer and text.count(name) <= sum(text.count(o) for o in longer):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
            "VALUES (?, ?, 'stock', 0.6)", (doc_id, eid))


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

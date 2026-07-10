"""적재: RawDoc → raw_documents + enrichments + entity_links.

content_hash로 멱등성 보장:
- 동일 문서 & 동일 내용 → skip (enrich 재실행 안 함 → LLM 비용 0)
- 내용 변경 → 갱신 후 이전 enrichment·링크 삭제하고 재enrich (stale 방지)
- keyword 티어 결과는 LLM 사용 가능해지면 자동 재enrich (백필)
"""
import hashlib
import json
import re

from database import get_connection
from pipeline.base import RawDoc
from pipeline.dates import to_iso_utc
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

    # [[엔티티명]] 위키링크 — 사람이 명시한 연결이므로 confidence 1.0 (노트 등)
    for name in set(re.findall(r"\[\[([^\]|#]+?)\]\]", text)):
        row = conn.execute(
            "SELECT id FROM entities WHERE name=? ORDER BY CASE type WHEN 'company' THEN 0 ELSE 1 END LIMIT 1",
            (name.strip(),),
        ).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                "VALUES (?, ?, 'mention', 1.0)", (doc_id, row["id"]))
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
    # 사용자 정의 키워드 — 결정적 매칭 (LLM 결과와 무관하게 항상 적용, conf 0.7)
    # proposed(자동 제안)는 승인 전까지 매칭에 쓰지 않는다
    for row in conn.execute(
        """SELECT ek.entity_id, ek.keyword FROM entity_keywords ek
           WHERE ek.status = 'active' OR ek.status IS NULL"""
    ).fetchall():
        kw = (row["keyword"] or "").strip()
        if not kw or kw not in text:
            continue
        pat = rf"(?<![0-9A-Za-z가-힣]){re.escape(kw)}"
        if len(kw) <= 2:
            pat += r"(?![0-9A-Za-z가-힣])"
        if re.search(pat, text):
            conn.execute(
                "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                "VALUES (?, ?, 'stock', 0.7)", (doc_id, row["entity_id"]))

    # 종목 (1순위): LLM이 별칭까지 정규화한 종목명 — substring 매칭을 대체 (conf 0.9)
    if result.get("stocks") is not None:
        for name in result["stocks"]:
            row = conn.execute(
                "SELECT id FROM entities WHERE type='company' AND name=?", (str(name).strip(),)
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                    "VALUES (?, ?, 'stock', 0.9)", (doc_id, row["id"]))

        # 별칭 자동 학습: LLM이 발견한 표기를 proposed 키워드로 축적 (승인 후 매칭 편입)
        for al in result.get("stock_aliases") or []:
            alias = (al.get("alias") or "").strip()
            if not alias or len(alias) < 2 or len(alias) > 20 or alias == al.get("name"):
                continue
            row = conn.execute(
                "SELECT id FROM entities WHERE type='company' AND name=?", (al.get("name"),)
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO entity_keywords (entity_id, keyword, status) "
                    "VALUES (?, ?, 'proposed')", (row["id"], alias))
        return

    # 종목 (fallback): 기존 company 엔티티 이름이 본문에 등장하면 링크.
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


def _enrich_and_store(conn, doc_id: int, title: str, md: str, h: str) -> dict:
    """이전 enrichment·링크 제거 후 재생성 — 문서당 정확히 1개 유지, stale 방지.

    LLM 호출(수 초~수십 초)은 반드시 쓰기 트랜잭션 밖에서 — DELETE를 LLM 뒤에 둬서
    쓰기 락 점유를 밀리초로 유지한다 (cron enrich 중 API 'database is locked' 방지).
    """
    result = enrich_mod.enrich(title, md)
    conn.execute("DELETE FROM enrichments WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM entity_links WHERE doc_id=?", (doc_id,))
    conn.execute(
        "INSERT INTO enrichments (doc_id, summary, sentiment, model, content_hash) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_id, result.get("summary"), result.get("sentiment"),
         result.get("model", "keyword"), h),
    )
    _link(conn, doc_id, title, md, result)
    conn.commit()
    return result


def reenrich_document(doc_id: int) -> str | None:
    """단일 문서 재enrich (백필용). 반환: 사용된 모델명."""
    conn = get_connection()
    row = conn.execute(
        "SELECT title, markdown, content_hash FROM raw_documents WHERE id=?", (doc_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    result = _enrich_and_store(conn, doc_id, row["title"] or "", row["markdown"] or "",
                               row["content_hash"] or "")
    conn.close()
    return result.get("model")


def store_document(doc: RawDoc) -> dict:
    md = to_markdown(doc)
    h = _hash(md)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, content_hash FROM raw_documents WHERE source_type=? AND source_id=?",
        (doc.source_type, doc.source_id),
    ).fetchone()

    media = json.dumps(doc.images) if doc.images else None
    if existing and existing["content_hash"] == h:
        # 내용 동일 — 문서는 그대로 두되, enrich 체크는 계속 진행
        # (keyword→LLM 백필이 여기서 일어난다). 미디어는 새로 잡히면 갱신.
        doc_id, status = existing["id"], "unchanged"
        if media:
            conn.execute("UPDATE raw_documents SET media_json=? WHERE id=? AND (media_json IS NULL OR media_json != ?)",
                         (media, doc_id, media))
    elif existing:
        conn.execute(
            "UPDATE raw_documents SET title=?, url=?, published_at=?, raw_content=?, "
            "markdown=?, content_hash=?, media_json=?, fetched_at=datetime('now') WHERE id=?",
            (doc.title, doc.url, to_iso_utc(doc.published_at), doc.raw_content, md, h, media, existing["id"]),
        )
        doc_id, status = existing["id"], "updated"
    else:
        cur = conn.execute(
            "INSERT INTO raw_documents (source_type, source_id, title, url, published_at, "
            "raw_content, markdown, content_hash, media_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.source_type, doc.source_id, doc.title, doc.url, to_iso_utc(doc.published_at),
             doc.raw_content, md, h, media),
        )
        doc_id, status = cur.lastrowid, "new"
    conn.commit()

    # enrich 필요 판정:
    # - 현재 내용(hash)에 대한 enrichment가 없거나
    # - keyword 티어 결과인데 LLM이 사용 가능해졌으면 (백필)
    cached = conn.execute(
        "SELECT model FROM enrichments WHERE doc_id=? AND content_hash=?", (doc_id, h)
    ).fetchone()
    needs_enrich = cached is None or (cached["model"] == "keyword" and enrich_mod.llm_available())

    if needs_enrich:
        _enrich_and_store(conn, doc_id, doc.title, md, h)

    conn.close()
    return {"doc_id": doc_id, "status": status}

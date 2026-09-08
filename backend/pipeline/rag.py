"""문서 검색 헬퍼 — 청크 하이브리드 + 리랭크 + 뮤트·기간·소스·엔티티 필터 (docs/specs/chat-retrieval.md).

종합(질의응답 생성)은 D-131에서 pipeline/chat.py로 이동했다. 이 모듈은 `search_docs` 도구가 쓰는
검색 반쪽: D-132부터 청크 인덱스(pipeline/chunks.py)에서 문서별 최고 청크를 뽑고 로컬 리랭커로
정렬한다. 근거 발췌는 '문서 앞 1,200자'가 아니라 '질문과 맞는 청크(+문맥 접두어)'.
"""
from datetime import date, timedelta

from database import get_connection
from pipeline.search import search

TOP_K = 12
EXCERPT_CHARS = 1200
CANDIDATES = 40   # 리랭커 후보 상한
MIN_CHUNK_CHARS = 80  # 이보다 짧은 청크(단문 답글·이모지)는 근거 후보에서 제외
RERANK_CHARS = 600  # 리랭커 입력 절단 — 크로스인코더 지연은 길이에 비례, 판별엔 접두어+앞부분으로 충분


def _fetch_docs(doc_ids: list[int]) -> list[dict]:
    if not doc_ids:
        return []
    conn = get_connection()
    ph = ",".join("?" for _ in doc_ids)
    rows = {r["id"]: r for r in conn.execute(f"""
        SELECT id, source_type, source_id, title, url, published_at, substr(markdown, 1, {EXCERPT_CHARS}) excerpt
        FROM raw_documents WHERE id IN ({ph})""", doc_ids)}
    conn.close()
    return [dict(rows[d]) for d in doc_ids if d in rows]  # 검색 랭킹 순 유지


def retrieve_docs(query: str, k: int = TOP_K, since_days: int | None = None,
                  source: str | None = None, entity_id: int | None = None) -> list[dict]:
    """청크 경로(D-132): 청크 하이브리드 → 문서별 최고 청크 → 필터 → 리랭크 → 상위 k, excerpt=접두어+청크.
    청크 인덱스가 비어 있으면 문서 경로(제목+앞 1,200자)로 폴백."""
    from pipeline.chunks import chunk_index_ready, search_chunks
    if not chunk_index_ready():
        return _retrieve_docs_legacy(query, k, since_days, source, entity_id)

    # 날짜·소스·엔티티 필터가 후보의 대부분을 걸러내면 찌꺼기(짧은 잡담 청크)만 남아 인용된다 —
    # 필터가 있으면 후보 풀을 넉넉히 뽑고, 짧은 청크(단문 답글·이모지)는 후보에서 뺀다
    filtered = bool(since_days or source or entity_id)
    hits = [h for h in search_chunks(query, k=CANDIDATES * (4 if filtered else 1), pool=320 if filtered else 80)
            if len(h.get("text") or "") >= MIN_CHUNK_CHARS]
    if not hits:
        return []
    docs = _fetch_docs([h["doc_id"] for h in hits])
    by_id = {d["id"]: d for d in docs}
    cands = []
    for h in hits:
        d = by_id.get(h["doc_id"])
        if d:
            d = dict(d)
            d["excerpt"] = f"{h['prefix']}\n{h['text']}"[:EXCERPT_CHARS + 300]
            d["chunk_id"] = h["chunk_id"]
            cands.append(d)
    cands = _dedupe(_apply_filters(cands, since_days, source, entity_id))[:CANDIDATES]
    if not cands:
        return []
    from pipeline.rerank import rerank
    scores = rerank(query, [c["excerpt"][:RERANK_CHARS] for c in cands])
    if scores is not None:
        cands = [c for _, c in sorted(zip(scores, cands), key=lambda t: -t[0])]
        for c, sc in zip(cands, sorted(scores, reverse=True)):
            c["rerank_score"] = round(sc, 3)
    return cands[:k]


def _dedupe(docs: list[dict]) -> list[dict]:
    """같은 글이 다른 채널·재전송으로 여러 문서로 들어온 경우(제목+본문 앞부분 동일) 하나만."""
    seen, out = set(), []
    for d in docs:
        key = ((d.get("title") or "").strip(), (d.get("excerpt") or "")[:200].split("\n", 1)[-1][:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _apply_filters(docs: list[dict], since_days, source, entity_id) -> list[dict]:
    from pipeline.visibility import get_muted, is_muted
    conn = get_connection()
    muted = get_muted(conn)
    linked: set[int] | None = None
    if entity_id:
        linked = {r["doc_id"] for r in conn.execute(
            "SELECT doc_id FROM entity_links WHERE entity_id=?", (entity_id,))}
    conn.close()
    since = (date.today() - timedelta(days=int(since_days))).isoformat() if since_days else None
    out = []
    for d in docs:
        if is_muted(d["source_type"], d.get("source_id", ""), d["url"], muted):
            continue
        if source and d["source_type"] != source:
            continue
        if since and (d["published_at"] or "")[:10] < since:
            continue
        if linked is not None and d["id"] not in linked:
            continue
        out.append(d)
    return out


def _retrieve_docs_legacy(query: str, k: int, since_days, source, entity_id) -> list[dict]:
    """문서 단위 검색(제목+앞 1,200자) — 청크 인덱스 첫 빌드 전 폴백."""
    pool = k + 8 + (24 if (since_days or source or entity_id) else 0)
    hits = search(query, k=pool)
    docs = _apply_filters(_fetch_docs([h["doc_id"] for h in hits]), since_days, source, entity_id)
    return docs[:k]

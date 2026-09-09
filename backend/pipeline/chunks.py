"""청크 인덱스 — 문단 경계 청킹 + 문맥 접두어(LLM 0) + BM25/벡터 (docs/specs/chat-retrieval.md, D-132).

- 문서 ≤ SINGLE_MAX 자는 1청크. 장문은 문단 경계로 CHUNK_CHARS 근처에서 끊고 OVERLAP만큼 겹친다.
- 접두어 = "[소스·날짜] 제목 — 요약" (enrichments.summary 재사용). Anthropic Contextual Retrieval의
  '청크를 문서 안에 위치시키기'를 이미 낸 비용으로 얻는다. 임베딩·BM25 둘 다 접두어+본문에 건다.
- 멱등: doc_chunks.content_hash == raw_documents.content_hash 면 스킵. 변경·신규만 재청킹·재임베딩.
- 피드 검색(search.py, 문서 단위)은 그대로. 여기는 대화 근거 전용.
"""
import re
import struct

from database import get_connection
from pipeline.search import EMBED_DIM, _get_model, _vec_conn

SINGLE_MAX = 1500
CHUNK_CHARS = 1200
OVERLAP = 150
MAX_CHUNKS_PER_DOC = 80
SUMMARY_CHARS = 160

_SOURCE_LABEL = {"telegram": "텔레그램", "blog": "블로그", "youtube": "유튜브", "transcript": "컨콜",
                 "canon": "정전", "note": "메모",
                 # 미검증 — 개인 투자자 블로그 스크랩. 라벨이 근거 텍스트에 그대로 실려 종합이 읽는다 (D-142)
                 "scrap": "스크랩(미검증)"}


def chunk_text(text: str) -> list[str]:
    """문단 경계 우선 청킹. 반환: 청크 텍스트 목록(≥1)."""
    text = (text or "").strip()
    if len(text) <= SINGLE_MAX:
        return [text] if text else []
    paras = [p.strip() for p in re.split(r"\n{2,}|\n(?=[#\-\*•\d])", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > CHUNK_CHARS + 400:            # 거대 문단은 하드 분할
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(p), CHUNK_CHARS - OVERLAP):
                chunks.append(p[i:i + CHUNK_CHARS])
                if len(chunks) >= MAX_CHUNKS_PER_DOC:
                    return chunks
            continue
        if buf and len(buf) + 1 + len(p) > CHUNK_CHARS:
            chunks.append(buf)
            buf = buf[-OVERLAP:] + "\n" + p if OVERLAP else p   # 겹침: 직전 꼬리
        else:
            buf = (buf + "\n" + p) if buf else p
        if len(chunks) >= MAX_CHUNKS_PER_DOC:
            return chunks
    if buf and (not chunks or len(buf) > OVERLAP + 40):
        chunks.append(buf)
    return chunks[:MAX_CHUNKS_PER_DOC]


def make_prefix(source_type: str, published_at: str | None, title: str | None, summary: str | None) -> str:
    head = f"[{_SOURCE_LABEL.get(source_type, source_type)}·{(published_at or '')[:10]}] {(title or '').strip()}"
    s = (summary or "").strip().replace("\n", " ")
    return head + (f" — {s[:SUMMARY_CHARS]}" if s else "")


def _serialize(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _ensure_tables(vconn) -> None:
    vconn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(embedding float[{EMBED_DIM}])")


def build_chunk_index(batch: int = 64, limit_docs: int | None = None) -> dict:
    """변경·신규 문서만 재청킹 → chunk_fts·chunk_vec 갱신. 고아 청크(삭제 문서) 정리. cron 체인에서 실행."""
    vconn = _vec_conn()
    if vconn is None:
        return {"chunks": 0, "docs": 0, "vec": "unavailable"}
    _ensure_tables(vconn)
    conn = vconn  # 같은 연결로 doc_chunks·chunk_fts·chunk_vec 처리 (단일 트랜잭션 단위: 문서)

    # 고아 정리
    orphans = [r[0] for r in conn.execute(
        "SELECT DISTINCT c.doc_id FROM doc_chunks c LEFT JOIN raw_documents rd ON rd.id=c.doc_id WHERE rd.id IS NULL")]
    for did in orphans:
        _delete_doc_chunks(conn, did)
    if orphans:
        conn.commit()

    todo = conn.execute(f"""
        SELECT rd.id, rd.source_type, rd.title, rd.published_at, rd.markdown, rd.content_hash, e.summary
        FROM raw_documents rd
        LEFT JOIN enrichments e ON e.doc_id = rd.id
        LEFT JOIN (SELECT doc_id, MIN(content_hash) h FROM doc_chunks GROUP BY doc_id) c ON c.doc_id = rd.id
        WHERE c.doc_id IS NULL OR c.h IS NULL OR c.h != rd.content_hash
        ORDER BY rd.id DESC {f'LIMIT {int(limit_docs)}' if limit_docs else ''}""").fetchall()
    model = _get_model() if todo else None
    n_chunks = 0
    pending: list[tuple[int, str]] = []   # (chunk_id, embed_text)

    def flush():
        nonlocal pending
        if not pending:
            return
        embs = model.embed([t for _, t in pending])
        for (cid, _), emb in zip(pending, embs):
            conn.execute("DELETE FROM chunk_vec WHERE rowid=?", (cid,))
            conn.execute("INSERT INTO chunk_vec (rowid, embedding) VALUES (?, ?)", (cid, _serialize(emb)))
        conn.commit()
        pending = []

    for r in todo:
        _delete_doc_chunks(conn, r["id"])
        prefix = make_prefix(r["source_type"], r["published_at"], r["title"], r["summary"])
        for idx, text in enumerate(chunk_text(r["markdown"] or "")):
            cid = conn.execute(
                "INSERT INTO doc_chunks (doc_id, idx, text, prefix, content_hash) VALUES (?,?,?,?,?)",
                (r["id"], idx, text, prefix, r["content_hash"])).lastrowid
            conn.execute("INSERT INTO chunk_fts (rowid, prefix, text) VALUES (?,?,?)", (cid, prefix, text))
            pending.append((cid, f"{prefix}\n{text}"))
            n_chunks += 1
        if len(pending) >= batch:
            flush()
    flush()
    total = conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]
    conn.close()
    return {"docs": len(todo), "chunks": n_chunks, "total_chunks": total, "orphans": len(orphans), "vec": "ok"}


def _delete_doc_chunks(conn, doc_id: int) -> None:
    ids = [r[0] for r in conn.execute("SELECT id FROM doc_chunks WHERE doc_id=?", (doc_id,))]
    for cid in ids:
        conn.execute("DELETE FROM chunk_fts WHERE rowid=?", (cid,))
        try:
            conn.execute("DELETE FROM chunk_vec WHERE rowid=?", (cid,))
        except Exception:
            pass
    conn.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))


def chunk_index_ready() -> bool:
    conn = get_connection()
    try:
        return conn.execute("SELECT 1 FROM doc_chunks LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def _fts_terms(texts: list[str], cap: int = 16) -> list[str]:
    """여러 검색어(원문+변형)에서 FTS 토큰 합집합 — 순서 보존·중복 제거."""
    out: list[str] = []
    for t in texts:
        for tok in re.split(r"[^0-9A-Za-z가-힣]+", t or ""):
            if len(tok) >= 2 and tok.lower() not in {o.lower() for o in out}:
                out.append(tok)
    return out[:cap]


def search_chunks(q: str, k: int = 40, pool: int = 80, variants: list[str] | None = None,
                  must_any: list[str] | None = None) -> list[dict]:
    """청크 하이브리드 검색 → 문서별 최고 청크. 반환 [{doc_id, chunk_id, score, prefix, text}] (RRF 순).

    - variants: 검색어 변형(한/영/티커/약어, D-137) — BM25는 토큰 합집합, 벡터는 원문+변형 각각 임베딩해 RRF.
    - must_any: 엔티티 별칭 목록 — BM25에 `(별칭 OR …) AND (주제 토큰 OR …)`로 '엔티티 언급'을 요구한다.
      별칭만 OR로 섞으면 엔티티만 자주 나오는 문서가 주제 문서를 밀어낸다. 결과가 적으면 주제 토큰만으로 보강.
    - RRF + 모달리티 쿼터(search.search와 같은 규율): 각 모달리티 상위 pool/4는 반드시 포함.
    """
    ranks: dict[int, float] = {}
    fts_ids: list[int] = []
    vec_ids: list[int] = []
    queries = [q] + [v for v in (variants or []) if v and v.strip() and v.strip() != q.strip()][:3]

    topic = _fts_terms(queries)
    topic_q = " OR ".join(f'"{t}"*' for t in topic) or '""'
    fts_queries = []
    if must_any:
        # 별칭 토큰: 'SK Hynix Inc.'→SK·Hynix·Inc 로 갈라지면 'SK'가 SK그룹 전체를 잡는다 — 2자 이하 ASCII는 제외
        alias_toks = [a for a in _fts_terms(must_any, cap=12) if len(a) >= 3 or re.search(r"[가-힣]", a)]
        ent_q = " OR ".join(f'"{a}"*' for a in alias_toks) or '""'
        fts_queries.append(f"({ent_q}) AND ({topic_q})")
    fts_queries.append(topic_q)

    conn = get_connection()
    for fq in fts_queries:
        try:
            rows = conn.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY rank LIMIT ?",
                                (fq, pool)).fetchall()
        except Exception:
            rows = []
        for i, r in enumerate(rows):
            ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + 1 / (60 + i)
            if r["rowid"] not in fts_ids:
                fts_ids.append(r["rowid"])
        if len(rows) >= pool // 4:      # 엔티티 제한 질의가 충분히 나오면 주제-only는 생략
            break
    conn.close()

    vconn = _vec_conn()
    if vconn is not None:
        try:
            has = vconn.execute("SELECT count(*) FROM chunk_vec").fetchone()[0]
        except Exception:
            has = 0
        if has:
            embs = list(_get_model().embed(queries))
            for j, emb in enumerate(embs):
                vrows = vconn.execute("SELECT rowid FROM chunk_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                                      (_serialize(emb), pool)).fetchall()
                w = 1.0 if j == 0 else 0.7        # 변형은 원문보다 약하게
                for i, r in enumerate(vrows):
                    ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + w / (60 + i)
                    if r["rowid"] not in vec_ids:
                        vec_ids.append(r["rowid"])
        vconn.close()
    if not ranks:
        return []

    quota = max(1, pool // 4)
    guaranteed = set(fts_ids[:quota]) | set(vec_ids[:quota])
    order = [c for c, _ in sorted(ranks.items(), key=lambda x: -x[1])]
    order = [c for c in order if c in guaranteed] + [c for c in order if c not in guaranteed]

    conn = get_connection()
    ph = ",".join("?" * len(order))
    meta = {r["id"]: r for r in conn.execute(
        f"SELECT id, doc_id, prefix, text FROM doc_chunks WHERE id IN ({ph})", order)}
    conn.close()

    out, seen_docs = [], set()
    for cid in order:
        m = meta.get(cid)
        if not m or m["doc_id"] in seen_docs:
            continue
        seen_docs.add(m["doc_id"])
        out.append({"doc_id": m["doc_id"], "chunk_id": cid, "score": ranks[cid], "prefix": m["prefix"], "text": m["text"]})
        if len(out) >= k:
            break
    return out

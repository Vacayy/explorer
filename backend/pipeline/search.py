"""하이브리드 검색 레이어 (Phase 2 RAG의 검색 반쪽).

- BM25: FTS5 doc_fts (database.py 트리거로 동기화)
- 벡터: sqlite-vec doc_vec + fastembed 로컬 임베딩 (다국어 MiniLM, 384d)
- 융합: RRF (Reciprocal Rank Fusion) — gbrain 패턴 차용
- 임베딩/확장 미가용 시 BM25 단독으로 graceful degrade

질의응답 생성(RAG의 나머지 반쪽)은 ANTHROPIC_API_KEY 확보 후:
검색 결과 + 출처 인용 + 갭 분석(인용 없는 주장·모순·오래된 문서)을 일급 출력으로.
"""
import re
import struct

from database import get_connection

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384
_model = None  # lazy singleton (로드 ~2초)


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def _vec_conn():
    """sqlite-vec 확장 로드된 연결. 미가용이면 None."""
    try:
        import sqlite_vec
    except ImportError:
        return None
    conn = get_connection()
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        conn.close()
        return None
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS doc_vec USING vec0(embedding float[{EMBED_DIM}])"
    )
    return conn


def _serialize(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def build_index(batch: int = 64) -> dict:
    """FTS 리빌드 + 임베딩 없는 문서 임베딩. cron 체인에서 주기 실행."""
    conn = get_connection()
    conn.execute("INSERT INTO doc_fts(doc_fts) VALUES('rebuild')")
    conn.commit()
    n_fts = conn.execute("SELECT count(*) FROM raw_documents").fetchone()[0]
    conn.close()

    vconn = _vec_conn()
    if vconn is None:
        return {"fts_docs": n_fts, "embedded": 0, "vec": "unavailable"}

    todo = vconn.execute("""
        SELECT id, title, substr(markdown, 1, 2000) md FROM raw_documents
        WHERE id NOT IN (SELECT rowid FROM doc_vec)
    """).fetchall()
    model = _get_model() if todo else None
    embedded = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        texts = [f"{r['title']}\n{r['md'] or ''}" for r in chunk]
        for row, emb in zip(chunk, model.embed(texts)):
            vconn.execute(
                "INSERT OR REPLACE INTO doc_vec (rowid, embedding) VALUES (?, ?)",
                (row["id"], _serialize(emb)),
            )
        vconn.commit()
        embedded += len(chunk)
    vconn.close()
    return {"fts_docs": n_fts, "embedded": embedded, "vec": "ok"}


def _fts_query(q: str) -> str:
    """사용자 입력 → FTS5 안전 질의 (토큰별 따옴표, prefix 매칭)."""
    tokens = [t for t in re.split(r"[\s]+", q.strip()) if t]
    return " ".join(f'"{t}"*' for t in tokens[:8])


def search(q: str, k: int = 20) -> list[dict]:
    """하이브리드 검색 → [{doc_id, score}] (RRF 순)."""
    ranks: dict[int, float] = {}

    # BM25
    conn = get_connection()
    try:
        fts_rows = conn.execute(
            "SELECT rowid FROM doc_fts WHERE doc_fts MATCH ? ORDER BY rank LIMIT 40",
            (_fts_query(q),),
        ).fetchall()
    except Exception:
        fts_rows = []
    conn.close()
    for i, r in enumerate(fts_rows):
        ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + 1 / (60 + i)

    # 벡터
    vconn = _vec_conn()
    if vconn is not None:
        has_vec = vconn.execute("SELECT count(*) FROM doc_vec").fetchone()[0]
        if has_vec:
            q_emb = list(_get_model().embed([q]))[0]
            vec_rows = vconn.execute(
                "SELECT rowid FROM doc_vec WHERE embedding MATCH ? AND k = 40 ORDER BY distance",
                (_serialize(q_emb),),
            ).fetchall()
            for i, r in enumerate(vec_rows):
                ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + 1 / (60 + i)
        vconn.close()

    ordered = sorted(ranks.items(), key=lambda x: -x[1])[:k]
    return [{"doc_id": doc_id, "score": score} for doc_id, score in ordered]


def related_docs(doc_id: int, k: int = 5) -> list[dict]:
    """임베딩 유사 문서 — 문서 디테일의 '관련 문서' (doc_vec 재사용, LLM 불필요)."""
    vconn = _vec_conn()
    if vconn is None:
        return []
    row = vconn.execute("SELECT embedding FROM doc_vec WHERE rowid = ?", (doc_id,)).fetchone()
    if not row:
        vconn.close()
        return []
    hits = vconn.execute(
        "SELECT rowid, distance FROM doc_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (row["embedding"], k + 1),
    ).fetchall()
    ids = [h["rowid"] for h in hits if h["rowid"] != doc_id][:k]
    if not ids:
        vconn.close()
        return []
    ph = ",".join("?" for _ in ids)
    rows = {r["id"]: r for r in vconn.execute(f"""
        SELECT id, source_type, title, published_at FROM raw_documents WHERE id IN ({ph})""", ids)}
    vconn.close()
    return [dict(rows[i]) for i in ids if i in rows]

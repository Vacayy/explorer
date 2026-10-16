"""하이브리드 검색 레이어 (Phase 2 RAG의 검색 반쪽).

- BM25: FTS5 doc_fts (database.py 트리거로 동기화)
- 벡터: sqlite-vec doc_vec + fastembed 로컬 임베딩 (다국어 MiniLM, 384d)
- 융합: RRF (Reciprocal Rank Fusion) — gbrain 패턴 차용
- 임베딩/확장 미가용 시 BM25 단독으로 graceful degrade

질의응답 생성(RAG의 나머지 반쪽)은 ANTHROPIC_API_KEY 확보 후:
검색 결과 + 출처 인용 + 갭 분석(인용 없는 주장·모순·오래된 문서)을 일급 출력으로.
"""
import math
import re
import struct

from database import get_connection

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384
_model = None  # lazy singleton (로드 ~2초)


def _get_model(*, local_files_only=False):
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        from config import FASTEMBED_CACHE
        _model = TextEmbedding(EMBED_MODEL, cache_dir=FASTEMBED_CACHE, local_files_only=local_files_only)
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
    # 임베딩 대상 문서의 content_hash 추적 — 내용이 바뀐 문서는 재임베딩
    # (vec0 가상테이블엔 부가 컬럼을 못 달아 별도 테이블로)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_vec_hash (rowid INTEGER PRIMARY KEY, content_hash TEXT)"
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

    # 신규(doc_vec에 없음) + 변경분(content_hash 불일치) 모두 재임베딩
    todo = vconn.execute("""
        SELECT rd.id, rd.title, substr(rd.markdown, 1, 2000) md, rd.content_hash
        FROM raw_documents rd
        LEFT JOIN doc_vec_hash h ON h.rowid = rd.id
        WHERE rd.id NOT IN (SELECT rowid FROM doc_vec)
           OR h.content_hash IS NULL OR h.content_hash != rd.content_hash
    """).fetchall()
    model = _get_model() if todo else None
    embedded = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        texts = [f"{r['title']}\n{r['md'] or ''}" for r in chunk]
        for row, emb in zip(chunk, model.embed(texts)):
            # vec0는 INSERT OR REPLACE 미지원 — 재임베딩(변경분)은 삭제 후 삽입
            vconn.execute("DELETE FROM doc_vec WHERE rowid=?", (row["id"],))
            vconn.execute(
                "INSERT INTO doc_vec (rowid, embedding) VALUES (?, ?)",
                (row["id"], _serialize(emb)),
            )
            vconn.execute(
                "INSERT OR REPLACE INTO doc_vec_hash (rowid, content_hash) VALUES (?, ?)",
                (row["id"], row["content_hash"]),
            )
        vconn.commit()
        embedded += len(chunk)
    vconn.close()
    return {"fts_docs": n_fts, "embedded": embedded, "vec": "ok"}


def _fts_query(q: str) -> str:
    """사용자 입력 → FTS5 안전 질의.

    - 구두점 기준 분해: "ADR(SKHY)" → ADR, SKHY (티커·괄호 표기가 통째로 죽지 않게)
    - OR 결합: 공백 결합(암묵 AND)은 문장형 질문에서 전멸을 부른다 —
      다중 토큰 매칭 문서는 BM25 rank가 알아서 상위로 올린다
    - 토큰별 prefix 매칭: "현황"*이 "현황을"(조사 붙은 형태)도 잡는다
    """
    raw = re.split(r"[^0-9A-Za-z가-힣]+", q)
    tokens = [t for t in raw if len(t) >= 2][:12]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"*' for t in tokens)


def search(q: str, k: int = 20) -> list[dict]:
    """하이브리드 검색 → [{doc_id, score}].

    융합: RRF + 모달리티별 상위 보장 쿼터(k/2) — 한쪽 헤드(예: 긴 질문에
    희석된 벡터)가 다른쪽의 정확한 중위 매치(예: BM25 8위의 티커 단문)를
    밀어내지 않도록, 각 모달리티 상위 k/2는 최종 결과에 반드시 포함한다.
    """
    ranks: dict[int, float] = {}
    fts_ids: list[int] = []
    vec_ids: list[int] = []

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
        fts_ids.append(r["rowid"])

    # 벡터
    vconn = _vec_conn()
    if vconn is not None:
        try:
            has_vec = vconn.execute("SELECT count(*) FROM doc_vec").fetchone()[0]
            if has_vec:
                # Interactive reads must not wait for a model download. Index building
                # remains responsible for warming the cache; BM25 is already available.
                q_emb = list(_get_model(local_files_only=True).embed([q]))[0]
                vec_rows = vconn.execute(
                    "SELECT rowid FROM doc_vec WHERE embedding MATCH ? AND k = 40 ORDER BY distance",
                    (_serialize(q_emb),),
                ).fetchall()
                for i, r in enumerate(vec_rows):
                    ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + 1 / (60 + i)
                    vec_ids.append(r["rowid"])
        except Exception:
            # Missing/corrupt embeddings never discard the lexical matches above.
            pass
        finally:
            vconn.close()

    half = max(1, k // 2)
    guaranteed = set(fts_ids[:half]) | set(vec_ids[:half])
    rrf_order = [d for d, _ in sorted(ranks.items(), key=lambda x: -x[1])]
    final = [d for d in rrf_order if d in guaranteed]          # 보장분 (RRF 순 유지)
    final += [d for d in rrf_order if d not in guaranteed]     # 나머지 RRF 순
    return [{"doc_id": d, "score": ranks[d]} for d in final[:k]]


RELATED_MIN_SIM = 0.65      # 이 아래는 5개를 채우려 억지로 붙이지 않는다(실측: 0.60~0.64는 무관한 글이 섞임)
RELATED_PER_SOURCE = 2      # 한 채널·블로그에서 최대 — 같은 채널 영상만 다섯 개 나오지 않게
RELATED_RECENCY_W = 0.03    # 발행 시점이 가까울수록 약간 가산(최대 +0.03, 30일 감쇠)
_REASON_KIND = {"stock": 0, "person": 1, "industry": 2}   # 주제(매크로·투자전략 등)는 너무 넓어 이유로 안 씀


def _norm_title(t: str | None) -> str:
    return re.sub(r"\s+", "", (t or "").lower())


def _days(a: str | None, b: str | None) -> float:
    from datetime import datetime
    try:
        return abs((datetime.fromisoformat(a[:10]) - datetime.fromisoformat(b[:10])).days)
    except (TypeError, ValueError):
        return 365.0


def _shared_entities(conn, doc_id: int, ids: list[int], cap: int = 3) -> dict[int, list[str]]:
    """겹치는 종목·인물·산업 — 드문 것 먼저. 낮은 확신 종목 매칭(0.6: '온'·'커서' 같은 일반어 오탐)은 뺀다."""
    def links(where, params):
        return conn.execute(f"""SELECT el.doc_id, el.entity_id, e.name, el.link_type FROM entity_links el
            JOIN entities e ON e.id = el.entity_id
            WHERE {where} AND el.link_type IN ('stock','person','industry')
              AND (el.link_type != 'stock' OR el.confidence >= 0.7)""", params).fetchall()
    mine = {r["entity_id"]: r for r in links("el.doc_id = ?", (doc_id,))}
    if not mine or not ids:
        return {}
    ph = ",".join("?" * len(ids))
    df = {r[0]: r[1] for r in conn.execute(
        f"SELECT entity_id, count(*) FROM entity_links WHERE entity_id IN ({','.join('?' * len(mine))}) GROUP BY 1", list(mine))}
    out: dict[int, list[tuple]] = {}
    for r in links(f"el.doc_id IN ({ph})", ids):
        if r["entity_id"] in mine and r["name"] not in [x[2] for x in out.get(r["doc_id"], [])]:
            out.setdefault(r["doc_id"], []).append((_REASON_KIND[r["link_type"]], df.get(r["entity_id"], 0), r["name"]))
    return {d: [n for *_, n in sorted(v)[:cap]] for d, v in out.items()}


def related_docs(doc_id: int, k: int = 5) -> list[dict]:
    """문서 디테일 '관련 문서' — 문서 대표 벡터(청크 평균, D-221) 유사도 + 정리 규칙(LLM 0).

    유사도 RELATED_MIN_SIM 미만 제외 · 같은 제목 1개 · 출처당 RELATED_PER_SOURCE개 · 발행 시점 근접 소폭 가산.
    각 항목에 겹치는 종목·인물·산업(reasons)을 붙인다."""
    from pipeline.sources import source_names
    vconn = _vec_conn()
    if vconn is None:
        return []
    try:
        try:
            row = vconn.execute("SELECT embedding FROM doc_centroid_vec WHERE rowid = ?", (doc_id,)).fetchone()
        except Exception:   # 청크 인덱스가 아직 없음
            row = None
        if not row:
            return []
        hits = vconn.execute(
            "SELECT rowid, distance FROM doc_centroid_vec WHERE embedding MATCH ? AND k = 60 ORDER BY distance",
            (row["embedding"],)).fetchall()
        sims = {h["rowid"]: 1 - h["distance"] ** 2 / 2 for h in hits if h["rowid"] != doc_id}   # 정규화 벡터: L2 → 코사인
        sims = {d: s for d, s in sims.items() if s >= RELATED_MIN_SIM}
        if not sims:
            return []
        ph = ",".join("?" * (len(sims) + 1))
        meta = {r["id"]: r for r in vconn.execute(
            f"SELECT id, source_type, source_id, url, title, published_at FROM raw_documents WHERE id IN ({ph})",
            [doc_id, *sims])}
        if doc_id not in meta:
            return []
        me = meta[doc_id]
        channels = source_names(vconn, list(meta.values()))
        ranked = sorted((d for d in sims if d in meta), key=lambda d: -(
            sims[d] + RELATED_RECENCY_W * math.exp(-_days(meta[d]["published_at"], me["published_at"]) / 30)))
        out, titles, per_source = [], {_norm_title(me["title"])}, {}
        for d in ranked:
            t, ch = _norm_title(meta[d]["title"]), (channels.get(d) or {}).get("name")
            if (t and t in titles) or (ch and per_source.get(ch, 0) >= RELATED_PER_SOURCE):
                continue
            titles.add(t)
            if ch:
                per_source[ch] = per_source.get(ch, 0) + 1
            out.append(d)
            if len(out) >= k:
                break
        reasons = _shared_entities(vconn, doc_id, out)
        return [{"id": d, "source_type": meta[d]["source_type"], "title": meta[d]["title"],
                 "published_at": meta[d]["published_at"], "channel": (channels.get(d) or {}).get("name"),
                 "similarity": round(sims[d], 3), "reasons": reasons.get(d, [])} for d in out]
    finally:
        vconn.close()

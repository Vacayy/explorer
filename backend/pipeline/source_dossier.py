"""소스(채널/블로그) 관점 프로필 — 게으른 생성 (docs/specs/source-dossier.md).

- 생성 시점: 사람이 도시에를 열람/호출할 때
- 재생성 가드: 지난 프로필 이후 문서 집합이 바뀐 경우에만 LLM 호출 (doc_ids_hash)
- LLM 호출은 트랜잭션 밖 (database lock 방지 원칙)
"""
import hashlib
import json
import threading

from database import get_connection
from pipeline.digests import STYLE_RULES, _call_json
from pipeline.enrich import llm_engine

PROFILE_DOCS = 40   # 프로필 입력으로 쓰는 최근 문서 수
EXCERPT = 500

# 소스별 in-flight 락 — 같은 소스에 생성 요청이 겹치면 뒤엣것은 앞 생성을 기다렸다
# 캐시를 받는다 (LLM 중복 호출 방지). sync 엔드포인트는 threadpool에서 돌아 블로킹 OK.
_locks_guard = threading.Lock()
_locks: dict[tuple[str, str], threading.Lock] = {}


def _profile_lock(kind: str, key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((kind, key), threading.Lock())


def resolve_source(conn, kind: str, key: str) -> dict | None:
    """레지스트리에서 소스 조회. 미등록이면 None."""
    if kind == "telegram":
        r = conn.execute(
            "SELECT channel_name, display_name, is_active FROM telegram_channels WHERE channel_name=?",
            (key,)).fetchone()
        if r:
            return {"kind": "telegram", "key": r["channel_name"],
                    "name": r["display_name"] or r["channel_name"], "author": None,
                    "is_active": bool(r["is_active"])}
    elif kind == "blog":
        r = conn.execute(
            "SELECT url, blog_name, author, is_active FROM blog_sources WHERE url=?",
            (key,)).fetchone()
        if r:
            return {"kind": "blog", "key": r["url"],
                    "name": r["blog_name"] or r["url"], "author": r["author"],
                    "is_active": bool(r["is_active"])}
    return None


def _doc_filter(kind: str) -> str:
    """raw_documents에서 이 소스의 문서를 고르는 WHERE 조각 (health와 동일 매칭)."""
    if kind == "telegram":
        return "source_type='telegram' AND source_id LIKE ? || '/%'"
    return "source_type='blog' AND url LIKE ? || '%'"


def recent_docs(conn, kind: str, key: str, limit: int):
    return conn.execute(f"""
        SELECT id, title, published_at, substr(markdown, 1, ?) ex
        FROM raw_documents WHERE {_doc_filter(kind)}
        ORDER BY published_at DESC LIMIT ?
    """, (EXCERPT, key, limit)).fetchall()


def profile_hash(docs) -> str:
    return hashlib.sha256("|".join(sorted(str(d["id"]) for d in docs)).encode()).hexdigest()


def get_cached(conn, kind: str, key: str):
    return conn.execute(
        "SELECT digest, insights, doc_count, doc_ids_hash, created_at FROM source_digests WHERE kind=? AND key=?",
        (kind, key)).fetchone()


def compute_profile(kind: str, key: str) -> dict:
    """stale이면 haiku로 관점 프로필 생성, 아니면 캐시 반환.

    반환: {status: fresh|cached|empty|unavailable|failed, digest, insights, created_at, doc_count}
    """
    with _profile_lock(kind, key):
        return _compute_profile_locked(kind, key)


def _compute_profile_locked(kind: str, key: str) -> dict:
    conn = get_connection()
    src = resolve_source(conn, kind, key)
    if not src:
        conn.close()
        return {"status": "not_found"}

    docs = recent_docs(conn, kind, key, PROFILE_DOCS)
    if not docs:
        conn.close()
        return {"status": "empty", "digest": None, "insights": None,
                "created_at": None, "doc_count": 0}

    h = profile_hash(docs)
    cached = get_cached(conn, kind, key)
    if cached and cached["doc_ids_hash"] == h:
        conn.close()
        return {"status": "cached", "digest": cached["digest"], "insights": cached["insights"],
                "created_at": cached["created_at"], "doc_count": cached["doc_count"]}

    if llm_engine() != "claude-code":
        conn.close()
        return {"status": "unavailable",
                "digest": cached["digest"] if cached else None,
                "insights": cached["insights"] if cached else None,
                "created_at": cached["created_at"] if cached else None,
                "doc_count": cached["doc_count"] if cached else 0}

    prior = cached["digest"] if cached else None
    who = src["name"] + (f" (저자: {src['author']})" if src.get("author") else "")
    ctx = "\n\n".join(
        f"[{(d['published_at'] or '')[:10]}] {d['title'] or '(제목 없음)'}\n{d['ex'] or ''}" for d in docs)
    prior_block = f"\n\n[지난 프로필 — 변화 판단 기준]\n{prior}" if prior else ""
    prompt = (
        f"너는 리서치센터의 소스 큐레이터다. 아래는 구독 중인 소스 '{who}'의 최근 글 {len(docs)}건이다.\n"
        "이 소스의 프로필을 써라: ① 어떤 관점과 전문 영역을 가진 사람/채널인지 ② 무엇을 지속적으로 "
        "follow-up 해왔는지 ③ 최근 관심사의 흐름. 글을 개별 나열하지 말고 소스라는 인물의 맥락으로 종합해라.\n"
        + STYLE_RULES +
        'JSON만 출력: {"digest": "마크다운 프로필", "new_insights": "지난 프로필에 없던 새 관심사·시각 변화가 '
        '있으면 1~3문장, 없거나 지난 프로필이 없으면 null"}\n'
        f"{prior_block}\n\n[최근 글]\n{ctx}"
    )
    try:
        data = _call_json(prompt)  # LLM 호출 — 커넥션에 쓰기 트랜잭션 없음
    except Exception:
        conn.close()
        return {"status": "failed",
                "digest": prior, "insights": cached["insights"] if cached else None,
                "created_at": cached["created_at"] if cached else None,
                "doc_count": cached["doc_count"] if cached else 0}

    conn.execute("""
        INSERT INTO source_digests (kind, key, digest, insights, doc_count, doc_ids_hash, model)
        VALUES (?, ?, ?, ?, ?, ?, 'claude-code/haiku')
        ON CONFLICT(kind, key) DO UPDATE SET
            digest=excluded.digest, insights=excluded.insights, doc_count=excluded.doc_count,
            doc_ids_hash=excluded.doc_ids_hash, model=excluded.model, created_at=datetime('now')
    """, (kind, key, data.get("digest"), data.get("new_insights") or None, len(docs), h))
    conn.commit()
    row = get_cached(conn, kind, key)
    conn.close()
    return {"status": "fresh", "digest": row["digest"], "insights": row["insights"],
            "created_at": row["created_at"], "doc_count": row["doc_count"]}

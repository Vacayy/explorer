"""주제 내러티브 — '주목 주제'를 질문형 서사로 격상 (theme_surge 고도화).

키워드+요약을 넘어, 한 이슈가 '어디서 시작해 어디로 가는지'를 자연어 md로:
질문형 제목 → 3줄 요약 → 전개 타임라인 → 인과 구조 → 시나리오(긍/부정) → 종합 해석.
게으른 생성 + hash 가드(source_digests kind='narrative'). 심층 종합이라 opus.
"""
import hashlib
import json
import os
import subprocess

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

NARRATIVE_MODEL = os.getenv("NARRATIVE_MODEL", "opus")
DOCS = 25
EXCERPT = 500


def _resolve(conn, topic: str):
    return conn.execute(
        "SELECT id, name, type FROM entities WHERE type IN ('sector','theme') AND name=? "
        "AND status IS NOT 'merged'", (topic,)).fetchone()


def gather(conn, entity_id: int) -> list[dict]:
    """이 주제 문서 — 타임라인 재료, 시간순(오래된→최신)."""
    return [dict(r) for r in conn.execute(f"""
        SELECT rd.id, rd.title, rd.published_at, rd.source_type, substr(rd.markdown, 1, {EXCERPT}) ex
        FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.entity_id=? AND el.link_type IN ('industry','topic')
          AND rd.published_at >= datetime('now', '-30 days')
        ORDER BY rd.published_at ASC LIMIT {DOCS}""", (entity_id,))]


def _hash(docs: list[dict]) -> str:
    return hashlib.sha256("|".join(str(d["id"]) for d in docs).encode()).hexdigest()


def get_cached(conn, topic: str):
    return conn.execute(
        "SELECT digest, doc_ids_hash, created_at FROM source_digests "
        "WHERE kind='narrative' AND key=?", (topic,)).fetchone()


def _build_prompt(topic: str, docs: list[dict], knowledge: list[dict]) -> str:
    tl = "\n".join(f"- {(d['published_at'] or '')[:10]} ({d['source_type']}) {d['title']}"
                   f"\n  {(d['ex'] or '').strip()[:160]}" for d in docs)
    from pipeline.knowledge_recall import knowledge_block
    kn = knowledge_block(knowledge, "승격된 지식 — 검증된 전제")
    return (
        f"너는 1인 리서치센터의 전략가다. '{topic}'가 최근 시장에서 주목받는 화두다. "
        "아래 시간순 문서로 이 주제의 '내러티브'를 써라 — 키워드 나열이 아니라 하나의 서사.\n"
        'JSON만 출력: {"title": "질문형 제목", "narrative": "마크다운 본문"}\n'
        "title: 이 이슈를 관통하는 질문 (예: '메모리 슈퍼사이클은 어디까지 갈까?', "
        "'엔비디아의 HBM4 의존은 SK하이닉스에 무엇을 의미하나?'). 낚시성 금지, 핵심 긴장을 담아라.\n"
        "narrative 마크다운 구조 (섹션 고정):\n"
        "## 3줄 요약\n지금 이 주제에서 알아야 할 것 3줄 (불릿).\n"
        "## 전개 — 어떻게 여기까지 왔나\n문서 날짜를 근거로 이슈가 시작돼 전개된 흐름을 시간순 서술 "
        "(각 국면에 '무엇이 관측됐고 무엇이 바뀌었나').\n"
        "## 인과 구조\n무엇이 무엇으로 이어지는지 A → B → C 형태로 (핵심 연결고리와 수혜/피해 주체).\n"
        "## 시나리오\n**긍정 [확률%]** 트리거→결과 / **기본 [확률%]** / **부정 [확률%]** 트리거→결과. "
        "확률 합 100.\n"
        "## 종합 해석\n이 내러티브에서 지금 가장 중요한 긴장과, 판가름 낼 관전 포인트 1~2개.\n"
        "규율: 문서에 없는 사실 지어내지 말 것. 주장은 근거 문서 흐름에 기반. "
        "'화자/시장은 ~로 본다'로 관측과 사실 구분. 전체 800자 내외, 밀도 높게.\n"
        f"{kn}\n\n[시간순 문서]\n{tl}"
    )


def _call(prompt: str) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", NARRATIVE_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=400)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def compute_narrative(topic: str) -> dict:
    conn = get_connection()
    ent = _resolve(conn, topic)
    if not ent:
        conn.close()
        return {"status": "not_found"}
    docs = gather(conn, ent["id"])
    if len(docs) < 3:
        conn.close()
        return {"status": "empty", "title": None, "narrative": None, "created_at": None}
    h = _hash(docs)
    cached = get_cached(conn, topic)
    if cached and cached["doc_ids_hash"] == h:
        conn.close()
        d = json.loads(cached["digest"])
        return {"status": "cached", "title": d.get("title"), "narrative": d.get("narrative"),
                "created_at": cached["created_at"]}
    if llm_engine() != "claude-code":
        conn.close()
        if cached:
            d = json.loads(cached["digest"])
            return {"status": "unavailable", "title": d.get("title"),
                    "narrative": d.get("narrative"), "created_at": cached["created_at"]}
        return {"status": "unavailable", "title": None, "narrative": None, "created_at": None}
    from pipeline.knowledge_recall import recall_for_query
    knowledge = recall_for_query(conn, topic)
    try:
        data = _call(_build_prompt(topic, docs, knowledge))
    except Exception:
        conn.close()
        return {"status": "failed", "title": None, "narrative": None, "created_at": None}
    payload = json.dumps({"title": data.get("title"), "narrative": data.get("narrative")}, ensure_ascii=False)
    conn.execute("""
        INSERT INTO source_digests (kind, key, digest, doc_count, doc_ids_hash, model, created_at)
        VALUES ('narrative', ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(kind, key) DO UPDATE SET
            digest=excluded.digest, doc_count=excluded.doc_count,
            doc_ids_hash=excluded.doc_ids_hash, model=excluded.model, created_at=excluded.created_at
    """, (topic, payload, len(docs), h, f"claude-code/{NARRATIVE_MODEL}"))
    conn.commit()
    conn.close()
    return {"status": "fresh", "title": data.get("title"), "narrative": data.get("narrative"),
            "created_at": None}


def cached_meta(conn, topic: str) -> dict:
    """GET용 — 캐시 여부·stale만 (LLM 없음)."""
    ent = _resolve(conn, topic)
    if not ent:
        return {"status": "not_found"}
    docs = gather(conn, ent["id"])
    cached = get_cached(conn, topic)
    if len(docs) < 3:
        return {"status": "empty"}
    stale = not cached or cached["doc_ids_hash"] != _hash(docs)
    if not cached:
        return {"status": "empty", "stale": True}
    d = json.loads(cached["digest"])
    return {"status": "cached", "title": d.get("title"), "narrative": d.get("narrative"),
            "created_at": cached["created_at"], "stale": stale}

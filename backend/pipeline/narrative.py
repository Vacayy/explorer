"""주제 내러티브 — '주목 주제'를 질문형 서사로 격상 (theme_surge 고도화).

키워드+요약을 넘어, 한 이슈가 '어디서 시작해 어디로 가는지'를 자연어 md로:
질문형 제목 → 3줄 요약 → 전개 타임라인 → 인과 구조 → 시나리오(긍/부정) → 종합 해석.
게으른 생성 + hash 가드(source_digests kind='narrative'). 심층 종합이라 opus.
"""
import hashlib
import json
import os
import re
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
    """이 주제 문서 — 재료, 수집(발행)순(오래된→최신). 시간 방향(D-021)도 함께.

    주의: published_at은 '글이 수집·작성된 날'이지 사건 발생일이 아니다.
    time_orientation(past/current/forward)으로 회고/현재/전망을 구분해 내러티브에 반영.
    """
    return [dict(r) for r in conn.execute(f"""
        SELECT rd.id, rd.title, rd.published_at, rd.source_type,
               en.time_orientation, en.reference_period,
               substr(rd.markdown, 1, {EXCERPT}) ex
        FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
        LEFT JOIN enrichments en ON en.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type IN ('industry','topic')
          AND rd.published_at >= datetime('now', '-30 days')
        ORDER BY rd.published_at ASC LIMIT {DOCS}""", (entity_id,))]


def _hash(docs: list[dict]) -> str:
    return hashlib.sha256("|".join(str(d["id"]) for d in docs).encode()).hexdigest()


def get_cached(conn, topic: str):
    return conn.execute(
        "SELECT digest, doc_ids_hash, created_at FROM source_digests "
        "WHERE kind='narrative' AND key=?", (topic,)).fetchone()


_ORIENT_KO = {"past": "회고", "current": "현재", "forward": "전망", "mixed": "회고+전망"}


def _build_prompt(topic: str, docs: list[dict], knowledge: list[dict]) -> str:
    def _mark(d):
        o = _ORIENT_KO.get(d.get("time_orientation") or "")
        ref = d.get("reference_period")
        tag = f"[{o}]" if o else "[시점미상]"
        if ref:
            tag += f"(대상: {ref})"
        return tag
    tl = "\n".join(f"- 수집 {(d['published_at'] or '')[:10]} {_mark(d)} ({d['source_type']}) {d['title']}"
                   f"\n  {(d['ex'] or '').strip()[:160]}" for d in docs)
    first = min((d["published_at"] or "")[:10] for d in docs) if docs else ""
    from pipeline.knowledge_recall import knowledge_block
    kn = knowledge_block(knowledge, "승격된 지식 — 검증된 전제")
    return (
        f"너는 1인 리서치센터의 전략가다. '{topic}'가 최근 시장에서 주목받는 화두다. "
        "아래 문서로 이 주제의 '내러티브'를 써라 — 키워드 나열이 아니라 하나의 서사.\n"
        "★시간 규율(가장 중요): 각 문서의 '수집 날짜'는 내가 그 글을 수집한 날일 뿐, "
        "사건이 실제로 일어난 날이 아니다. 각 문서에 [회고]/[현재]/[전망] 시간 방향과 "
        "(대상: 시기)가 붙어 있으니 이걸 반드시 구분하되 — [전망] 문서를 '방금 일어난 사건'처럼 "
        "쓰지 말고, 수집이 며칠 새 몰렸다고 '급격한 전개'로 과장하지 마라. "
        f"(이 주제 수집 시작: {first})\n"
        "★출력 규율(반드시): 본문에 '[현재]'·'[회고]'·'[전망]'·'[시점미상]' 같은 대괄호 태그를 "
        "절대 쓰지 마라. 그건 너에게 주는 입력 주석일 뿐이다. 시제·확실성은 자연스러운 한국어 "
        "문장으로 녹여라 — 현재형('~하고 있다'), 과거형('~했다'), 전망('~할 전망이다'/'~라는 예상이 "
        "나온다'), 검토('~을 검토 중이다'). "
        "예: '베이징의 자국 AI 해외접근 제한 [현재·검토 단계]이 상징' (나쁨) → "
        "'현재 베이징이 자국 AI 해외접근 제한을 검토 중인 것이 대표적 상징이다' (좋음).\n"
        'JSON만 출력: {"title": "질문형 제목", "narrative": "마크다운 본문"}\n'
        "title: 이 이슈를 관통하는 질문 (예: '메모리 슈퍼사이클은 어디까지 갈까?', "
        "'엔비디아의 HBM4 의존은 SK하이닉스에 무엇을 의미하나?'). 낚시성 금지, 핵심 긴장을 담아라.\n"
        "가독성 규율: 논리 단위마다 줄을 나눠라. 불릿은 각각 '- '로 시작하는 별도 줄, "
        "여러 갈래(①②)나 시나리오(긍정/기본/부정)는 각각 자기 줄에 둔다. 한 문단에 여러 논점을 "
        "몰아넣지 마라.\n"
        "narrative 마크다운 구조 (섹션 고정, 섹션 사이 빈 줄):\n"
        "## 3줄 요약\n핵심 3가지를 각각 '- ' 불릿 한 줄로.\n"
        "## 무엇이 다뤄지고 있나\n최근 '수집·논의된' 내용을 정리 — 날짜를 사건 발생일로 단정하지 말고 "
        "'언제 다뤄졌다/언급됐다'로. 실제 벌어진 일과 전망·논평을 자연스러운 시제로 구분(위 출력 규율). "
        "'회자되다'라는 표현은 쓰지 말고, 다뤄지다·언급되다·거론되다·이야기가 나오다·논의되다 등으로 "
        "다양하게(한 단어 반복 금지). 갈래가 둘 이상이면 '- ' 불릿으로 나눠라.\n"
        "## 인과 구조\n무엇이 무엇으로 이어지는지 'A → B → C' 한 줄로 쓰고, 그 아래 줄에 "
        "수혜/피해 주체를 짧게.\n"
        "## 시나리오\n세 줄, 각각 별도 불릿:\n- **긍정 (확률%)** 트리거 → 결과\n"
        "- **기본 (확률%)** 트리거 → 결과\n- **부정 (확률%)** 트리거 → 결과\n확률 합 100.\n"
        "## 종합 해석\n지금 가장 중요한 긴장 1문장 + 판가름 낼 관전 포인트 1~2개(각 '- ' 불릿).\n"
        "규율: 문서에 없는 사실 지어내지 말 것. 주장은 근거 문서 흐름에 기반. "
        "'화자/시장은 ~로 본다'로 관측과 사실 구분. 전체 800자 내외, 밀도 높게.\n"
        f"{kn}\n\n[수집된 문서 — '수집 날짜'는 발행일이지 사건 발생일이 아님. "
        f"대괄호 태그는 입력 주석일 뿐, 본문에 그대로 쓰지 말 것]\n{tl}"
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


def _summary(md: str | None) -> str | None:
    """내러티브 md에서 '3줄 요약' 섹션만 뽑아 한 줄로 (목록 미리보기용)."""
    if not md:
        return None
    m = re.search(r"##\s*3줄\s*요약\s*\n(.*?)(?=\n##|\Z)", md, re.S)
    body = m.group(1) if m else md
    lines = [ln.strip().lstrip("-*•").strip() for ln in body.strip().splitlines() if ln.strip()]
    return " · ".join(lines)[:200] or None


def _theme_metrics(conn) -> dict:
    """최신 theme_surge 신호 — 테마명→점유율 지표 (목록 랭킹·배지용)."""
    rows = conn.execute("""
        SELECT e.name, s.payload_json FROM signals s JOIN entities e ON e.id=s.entity_id
        WHERE s.signal_type='theme_surge'
          AND s.date=(SELECT MAX(date) FROM signals WHERE signal_type='theme_surge')
    """).fetchall()
    return {r["name"]: json.loads(r["payload_json"]) for r in rows}


def list_narratives(conn) -> list[dict]:
    """생성된 내러티브 목록 — 현재 급증 중인 주제 먼저(점유율 상승폭순), 나머지는 최신순."""
    metrics = _theme_metrics(conn)
    rows = conn.execute(
        "SELECT key, digest, created_at FROM source_digests "
        "WHERE kind='narrative' AND digest IS NOT NULL").fetchall()
    items = []
    for r in rows:
        d = json.loads(r["digest"])
        if not d.get("title"):
            continue
        m = metrics.get(r["key"])
        items.append({
            "topic": r["key"], "title": d.get("title"),
            "summary": _summary(d.get("narrative")),
            "share_pct": m.get("share_pct") if m else None,
            "share_delta_pp": m.get("share_delta_pp") if m else None,
            "is_new": bool(m.get("is_new")) if m else False,
            "is_surging": m is not None, "created_at": r["created_at"],
        })
    surging = sorted((x for x in items if x["is_surging"]),
                     key=lambda x: -(x["share_delta_pp"] or 0))
    rest = sorted((x for x in items if not x["is_surging"]),
                  key=lambda x: x["created_at"] or "", reverse=True)
    return surging + rest


def compute_top_narratives(limit: int = 5) -> dict:
    """cron 배치 — 현재 주목 상위 테마의 내러티브를 미리 생성 (사전 생성).
    theme_surge 최신 신호 상위 N개 → compute_narrative (멱등, hash 가드로 변경 시에만 opus)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.name FROM signals s JOIN entities e ON e.id=s.entity_id
        WHERE s.signal_type='theme_surge'
          AND s.date=(SELECT MAX(date) FROM signals WHERE signal_type='theme_surge')
        ORDER BY json_extract(s.payload_json,'$.share_delta_pp') DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    topics = [r["name"] for r in rows]
    results = {}
    for t in topics:
        try:
            results[t] = compute_narrative(t).get("status")
        except Exception as e:  # noqa: BLE001 — 배치라 한 주제 실패가 전체를 막지 않게
            results[t] = f"error:{str(e)[:80]}"
    return {"topics": topics, "results": results}


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

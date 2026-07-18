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


def _latest_narrative(conn, topic: str):
    return conn.execute(
        "SELECT * FROM narratives WHERE topic=? ORDER BY version DESC LIMIT 1", (topic,)).fetchone()


def _node_vocab(conn, limit: int = 60) -> list[str]:
    """인과 노드 정규화용 — 기존 노드 이름을 프롬프트에 주입해 파편화 방어 (live vocab)."""
    rows = conn.execute(
        "SELECT name FROM entities WHERE type IN ('sector','theme','macro','policy','event') "
        "AND status IS NOT 'merged' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [r["name"] for r in rows]


def _resolve_or_create_node(conn, name: str, type_: str) -> int | None:
    """인과 노드명 → entity id. 정확 이름 매칭 우선(타입 무관 재사용), 없으면 생성."""
    name = (name or "").strip()
    if not name or len(name) > 60:
        return None
    if type_ not in NODE_TYPES:
        type_ = "theme"
    row = conn.execute(
        "SELECT id FROM entities WHERE name=? ORDER BY CASE WHEN type=? THEN 0 ELSE 1 END LIMIT 1",
        (name, type_)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO entities (type, name) VALUES (?, ?)", (type_, name))
    return cur.lastrowid


def _persist_causal(conn, narrative_id: int, source_doc_id: int | None, causal: dict) -> int:
    """인과 노드·엣지를 entity_relations에 적재 (hypothesis). 같은 (src,dst,rel) 재적재는 confidence 강화."""
    ntype = {str(n.get("name")).strip(): (n.get("type") or "theme")
             for n in (causal.get("nodes") or []) if n.get("name")}
    made = 0
    for e in (causal.get("edges") or []):
        frm, to = (e.get("from") or "").strip(), (e.get("to") or "").strip()
        rel = e.get("rel") if e.get("rel") in CAUSAL_RELS else "CAUSES"
        if not frm or not to or frm == to:
            continue
        sid = _resolve_or_create_node(conn, frm, ntype.get(frm, "theme"))
        did = _resolve_or_create_node(conn, to, ntype.get(to, "theme"))
        if not sid or not did:
            continue
        try:
            conf = max(0.0, min(1.0, float(e.get("confidence")))) if e.get("confidence") is not None else 0.5
        except (TypeError, ValueError):
            conf = 0.5
        existing = conn.execute(
            "SELECT id, confidence FROM entity_relations WHERE src_id=? AND dst_id=? AND rel_type=?",
            (sid, did, rel)).fetchone()
        if existing:  # 반복 확인 → confidence 강화(상한 0.95), 최신 내러티브로 연결 (교차검증의 씨앗)
            conn.execute(
                "UPDATE entity_relations SET confidence=?, narrative_id=?, mechanism=COALESCE(?, mechanism) WHERE id=?",
                (min(0.95, (existing["confidence"] or conf) + 0.05), narrative_id, e.get("mechanism"), existing["id"]))
        else:
            conn.execute(
                "INSERT INTO entity_relations (src_id, dst_id, rel_type, epistemic_type, confidence, "
                "source_doc_id, mechanism, reference_period, time_orientation, narrative_id, valid_from) "
                "VALUES (?, ?, ?, 'hypothesis', ?, ?, ?, ?, ?, ?, datetime('now'))",
                (sid, did, rel, conf, source_doc_id, e.get("mechanism"),
                 e.get("reference_period"), e.get("orientation"), narrative_id))
            made += 1
    return made


def _persist_narrative(conn, topic: str, data: dict, docs: list[dict], h: str) -> tuple[int, int, int]:
    """새 버전 INSERT(이전 버전 supersede) + 인과 그래프 적재. 반환 (narrative_id, version, edges)."""
    prev = _latest_narrative(conn, topic)
    version = (prev["version"] + 1) if prev else 1
    if prev:
        conn.execute("UPDATE narratives SET superseded_at=datetime('now') WHERE id=?", (prev["id"],))
    cats = data.get("category") or []
    if isinstance(cats, str):
        cats = [cats]
    category = ",".join(c for c in (str(x).strip() for x in cats) if c in DOMAIN_LENSES) or None
    cur = conn.execute(
        "INSERT INTO narratives (topic, version, title, body, category, doc_count, doc_ids_hash, model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (topic, version, data.get("title"), data.get("narrative"), category, len(docs), h,
         f"claude-code/{NARRATIVE_MODEL}"))
    nid = cur.lastrowid
    made = _persist_causal(conn, nid, docs[-1]["id"] if docs else None, data.get("causal") or {})
    return nid, version, made


_ORIENT_KO = {"past": "회고", "current": "현재", "forward": "전망", "mixed": "회고+전망"}


DOMAIN_LENSES = {"macro", "geopolitics", "industry", "flow", "tech", "policy"}
NODE_TYPES = {"company", "sector", "theme", "person", "macro", "policy", "event"}
CAUSAL_RELS = {"CAUSES", "BENEFITS_FROM"}


def _build_prompt(topic: str, docs: list[dict], knowledge: list[dict], node_vocab: list[str]) -> str:
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
        'JSON만 출력: {"title": "질문형 제목", "narrative": "마크다운 본문", '
        '"category": ["도메인 렌즈"], "causal": {"nodes": [...], "edges": [...]}}\n'
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
        "'화자/시장은 ~로 본다'로 관측과 사실 구분. 전체 800자 내외, 밀도 높게.\n\n"
        "★인과 그래프 추출 (본문과 별도로 구조화 — 위 서사의 인과를 노드·엣지로):\n"
        "- category: 이 내러티브가 걸친 도메인 렌즈 1~3개 (아래 중에서만): "
        "macro·geopolitics·industry·flow·tech·policy\n"
        "- causal.nodes: 인과에 등장하는 핵심 노드. 각 {\"name\",\"type\",\"layer\"}.\n"
        "  type ∈ company·sector·theme·person·macro(유가·금리·인플레)·policy(협상·규제)·event(봉쇄·사고)\n"
        "  layer ∈ event·flow·cycle·structure·regime (느릴수록 구조적)\n"
        f"  ★기존 노드가 있으면 새로 만들지 말고 정확히 그 이름을 재사용: {', '.join(node_vocab[:60])}\n"
        "- causal.edges: 인과 고리. 각 "
        "{\"from\",\"to\",\"rel\",\"mechanism\",\"orientation\",\"reference_period\",\"confidence\"}.\n"
        "  rel='CAUSES'(원인→결과). 수혜 섹터는 rel='BENEFITS_FROM'(from=수혜 섹터, to=체인 말단 동인).\n"
        "  앞의 끝(근본 원인)은 policy/regime/structure 노드까지 거슬러라. "
        "뒤의 끝(수혜)은 sector까지만 — 개별 종목 금지.\n"
        "  orientation ∈ past|current|forward (원인은 대개 past, 수혜 효과는 forward).\n"
        "  reference_period: 이 인과가 작동하는 시점(수집일 아님, 예 '2026 하반기'), 모르면 null.\n"
        "  confidence: 0~1 (근거 강도). 원인→결과 방향만, 순환(사이클) 금지.\n"
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
    prev = _latest_narrative(conn, topic)
    if prev and prev["doc_ids_hash"] == h:
        conn.close()
        return {"status": "cached", "title": prev["title"], "narrative": prev["body"],
                "created_at": prev["created_at"]}
    if llm_engine() != "claude-code":
        conn.close()
        if prev:
            return {"status": "unavailable", "title": prev["title"],
                    "narrative": prev["body"], "created_at": prev["created_at"]}
        return {"status": "unavailable", "title": None, "narrative": None, "created_at": None}
    from pipeline.knowledge_recall import recall_for_query
    knowledge = recall_for_query(conn, topic)
    try:
        data = _call(_build_prompt(topic, docs, knowledge, _node_vocab(conn)))
    except Exception:
        conn.close()
        return {"status": "failed", "title": None, "narrative": None, "created_at": None}
    _persist_narrative(conn, topic, data, docs, h)
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
    """생성된 내러티브 목록(주제별 최신 버전) — 급증 주제 먼저, 나머지 최신순."""
    metrics = _theme_metrics(conn)
    rows = conn.execute("""
        SELECT n.* FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives GROUP BY topic) l
          ON l.topic=n.topic AND l.mv=n.version
        WHERE n.title IS NOT NULL""").fetchall()
    items = []
    for r in rows:
        m = metrics.get(r["topic"])
        items.append({
            "topic": r["topic"], "title": r["title"],
            "summary": _summary(r["body"]), "category": r["category"],
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


def causal_subgraph(conn, narrative_id: int) -> dict:
    """한 내러티브의 인과 서브그래프 — 노드·엣지 (프론트 구조 뷰용)."""
    edges = conn.execute("""
        SELECT er.rel_type, er.mechanism, er.reference_period, er.time_orientation, er.confidence,
               s.id sid, s.name sname, s.type stype, d.name dname, d.type dtype
        FROM entity_relations er
        JOIN entities s ON s.id=er.src_id JOIN entities d ON d.id=er.dst_id
        WHERE er.narrative_id=? AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
        ORDER BY er.id""", (narrative_id,)).fetchall()
    nodes: dict[int, dict] = {}
    out_edges = []
    for e in edges:
        nodes.setdefault(e["sid"], {"name": e["sname"], "type": e["stype"]})
        out_edges.append({"from": e["sname"], "from_type": e["stype"], "to": e["dname"],
                          "to_type": e["dtype"], "rel": e["rel_type"], "mechanism": e["mechanism"],
                          "orientation": e["time_orientation"], "reference_period": e["reference_period"],
                          "confidence": e["confidence"]})
    return {"nodes": list(nodes.values()), "edges": out_edges}


def _path_hash(path: dict) -> str:
    return hashlib.sha256("|".join(n["name"] for n in path["nodes"]).encode()).hexdigest()


def _build_mer_prompt(topic: str, path: dict) -> str:
    hops = []
    for i, e in enumerate(path["edges"]):
        o = _ORIENT_KO.get(e.get("orientation") or "", "시점미상")
        ref = f"(대상: {e['reference_period']})" if e.get("reference_period") else ""
        hops.append(f"{i + 1}. {e['from']} → {e['to']} [{o}{ref}] {e.get('mechanism') or ''}")
    chain_desc = "\n".join(hops)
    ending = "수혜 섹터" if path.get("reaches_sector") else "현재까지 파악된 끝"
    return (
        "너는 '메르'처럼 인과 체인을 근본 원인에서 결과까지 시간순으로 풀어 쓰는 애널리스트다. "
        f"아래는 인과 그래프 순회로 얻은 '{topic}' 관련 체인이다 — 이미 사실 검증된 구조이니 "
        "여기 없는 인과를 지어내지 말고, 주어진 체인만 하나의 흐르는 서사로 엮어라.\n"
        f"인과 체인(근본 원인 → … → {ending}):\n{chain_desc}\n\n"
        "규율: 각 단계의 메커니즘과 시간(회고/현재/전망)을 자연스러운 한국어 문장으로 녹여라. "
        "대괄호 태그를 본문에 그대로 쓰지 말 것. 근본 원인에서 시작해 논리적으로 다음 단계로 "
        "이어지는 하나의 글로 써라(400자 내외). 마지막 문장은 투자 함의로 닫아라.\n"
        'JSON만 출력: {"narrative": "..."}'
    )


def compute_mer_narrative(topic: str) -> dict:
    """순회 top-1 경로(근본원인→수혜)를 opus로 하나의 서사로 (Phase 2 §2-2). 경로 불변 시 캐시."""
    conn = get_connection()
    prev = _latest_narrative(conn, topic)
    if not prev:
        conn.close()
        return {"status": "empty", "narrative": None, "path": None}
    from pipeline.narrative_graph import narrative_chain
    chain = narrative_chain(conn, prev["id"], top_k=1)
    if chain["status"] != "ok" or not chain["paths"]:
        conn.close()
        return {"status": "empty", "narrative": None, "path": None}
    path = chain["paths"][0]
    h = _path_hash(path)
    if prev["mer_path_hash"] == h and prev["mer_body"]:
        conn.close()
        return {"status": "cached", "narrative": prev["mer_body"], "path": path}
    if llm_engine() != "claude-code":
        conn.close()
        return {"status": "unavailable", "narrative": prev["mer_body"], "path": path}
    try:
        data = _call(_build_mer_prompt(topic, path))
    except Exception:
        conn.close()
        return {"status": "failed", "narrative": None, "path": path}
    conn.execute("UPDATE narratives SET mer_body=?, mer_path_hash=? WHERE id=?",
                 (data.get("narrative"), h, prev["id"]))
    conn.commit()
    conn.close()
    return {"status": "fresh", "narrative": data.get("narrative"), "path": path}


def cached_mer_meta(conn, topic: str) -> dict:
    """GET용 — 캐시된 메르 서사 + stale만 (LLM 없음)."""
    prev = _latest_narrative(conn, topic)
    if not prev:
        return {"status": "empty", "narrative": None, "path": None, "stale": False}
    from pipeline.narrative_graph import narrative_chain
    chain = narrative_chain(conn, prev["id"], top_k=1)
    if chain["status"] != "ok" or not chain["paths"]:
        return {"status": "empty", "narrative": prev["mer_body"], "path": None, "stale": False}
    path = chain["paths"][0]
    h = _path_hash(path)
    stale = prev["mer_path_hash"] != h or not prev["mer_body"]
    return {"status": "empty" if stale else "cached", "narrative": prev["mer_body"],
            "path": path, "stale": stale}


def cached_meta(conn, topic: str) -> dict:
    """GET용 — 캐시 여부·stale만 (LLM 없음)."""
    ent = _resolve(conn, topic)
    if not ent:
        return {"status": "not_found"}
    docs = gather(conn, ent["id"])
    prev = _latest_narrative(conn, topic)
    if len(docs) < 3 and not prev:
        return {"status": "empty"}
    stale = not prev or prev["doc_ids_hash"] != _hash(docs)
    if not prev:
        return {"status": "empty", "stale": True}
    return {"status": "cached", "title": prev["title"], "narrative": prev["body"],
            "created_at": prev["created_at"], "stale": stale,
            "category": prev["category"], "version": prev["version"], "narrative_id": prev["id"]}

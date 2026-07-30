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


PACE_LAYERS = ("event", "flow", "cycle", "structure", "regime")


def _set_pace_layer(conn, entity_id: int, layer: str | None) -> None:
    """노드 중력(D-030) — 추출된 pace_layer를 meta_json에 저장. 이미 있으면 유지
    (문서마다 판정이 흔들릴 수 있어 최초 기록이 안정적 — 정정은 백필/수동으로)."""
    if layer not in PACE_LAYERS:
        return
    row = conn.execute("SELECT meta_json FROM entities WHERE id=?", (entity_id,)).fetchone()
    meta = json.loads(row["meta_json"]) if row and row["meta_json"] else {}
    if meta.get("pace_layer"):
        return
    meta["pace_layer"] = layer
    conn.execute("UPDATE entities SET meta_json=? WHERE id=?",
                 (json.dumps(meta, ensure_ascii=False), entity_id))


def _resolve_or_create_node(conn, name: str, type_: str, layer: str | None = None) -> int | None:
    """인과 노드명 → entity id. 정확 이름 매칭 우선(타입 무관 재사용), 없으면 생성.
    layer가 오면 meta_json.pace_layer에 기록 (노드 중력, D-030)."""
    name = (name or "").strip()
    if not name or len(name) > 60:
        return None
    if type_ not in NODE_TYPES:
        type_ = "theme"
    row = conn.execute(
        "SELECT id FROM entities WHERE name=? ORDER BY CASE WHEN type=? THEN 0 ELSE 1 END LIMIT 1",
        (name, type_)).fetchone()
    if row:
        eid = row["id"]
    else:
        # 정확 이름 매칭 실패 — 병합으로 사라진 이름이면 survivor로 해소 (D-033, 재파편화 방지)
        redirect = conn.execute(
            "SELECT survivor_id FROM entity_merges WHERE old_name=? AND type=?",
            (name, type_)).fetchone()
        eid = redirect["survivor_id"] if redirect else conn.execute(
            "INSERT INTO entities (type, name) VALUES (?, ?)", (type_, name)).lastrowid
    if layer:
        _set_pace_layer(conn, eid, layer)
    return eid


def _persist_causal(conn, narrative_id: int | None, source_doc_id: int | None, causal: dict,
                     conf_cap: float = 1.0, epistemic: str = "hypothesis") -> int:
    """인과 노드·엣지를 entity_relations에 적재. 같은 (src,dst,rel) 재적재는 confidence 강화.
    narrative_id=None이면 문서 레벨 추출(D-028 레버 3) — 근거 이력(narrative_edge_evidence)은 건너뛴다.
    conf_cap: 초기 confidence 상한 (문서 레벨은 0.5 — 반복 확인돼야 커진다).
    epistemic: 'hypothesis'(시장 가설, 기본) | 'observed'(canon 역사 해석 — 널리 수용된 사실 사슬, D-030)."""
    ntype = {str(n.get("name")).strip(): (n.get("type") or "theme")
             for n in (causal.get("nodes") or []) if n.get("name")}
    nlayer = {str(n.get("name")).strip(): n.get("layer")
              for n in (causal.get("nodes") or []) if n.get("name")}
    made = 0
    for e in (causal.get("edges") or []):
        frm, to = (e.get("from") or "").strip(), (e.get("to") or "").strip()
        rel = e.get("rel") if e.get("rel") in CAUSAL_RELS else "CAUSES"
        if not frm or not to or frm == to:
            continue
        sid = _resolve_or_create_node(conn, frm, ntype.get(frm, "theme"), nlayer.get(frm))
        did = _resolve_or_create_node(conn, to, ntype.get(to, "theme"), nlayer.get(to))
        if not sid or not did:
            continue
        try:
            conf = max(0.0, min(conf_cap, float(e.get("confidence")))) if e.get("confidence") is not None else 0.5
        except (TypeError, ValueError):
            conf = 0.5
        conf = min(conf, conf_cap)
        es = e.get("effect_strength") if e.get("effect_strength") in EFFECT_STRENGTHS else "unknown"
        ed = e.get("effect_direction") if e.get("effect_direction") in EFFECT_DIRECTIONS else None
        existing = conn.execute(
            "SELECT id, confidence FROM entity_relations WHERE src_id=? AND dst_id=? AND rel_type=?",
            (sid, did, rel)).fetchone()
        if existing:  # 반복 확인 → confidence 강화(상한 0.95), 최신 내러티브로 연결 (교차검증의 씨앗)
            # 문서 레벨 재확인(narrative_id=None)이 기존 내러티브 태그를 지우지 않게 COALESCE
            conn.execute(
                "UPDATE entity_relations SET confidence=?, narrative_id=COALESCE(?, narrative_id), "
                "mechanism=COALESCE(?, mechanism), geo_scope=COALESCE(geo_scope, ?), "
                "effect_strength=COALESCE(NULLIF(?, 'unknown'), effect_strength), "
                "effect_direction=COALESCE(?, effect_direction) WHERE id=?",
                (min(0.95, (existing["confidence"] or conf) + 0.05), narrative_id,
                 e.get("mechanism"), _norm_geo(e.get("geo")), es, ed, existing["id"]))
            rel_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO entity_relations (src_id, dst_id, rel_type, epistemic_type, confidence, "
                "effect_strength, effect_direction, "
                "source_doc_id, mechanism, reference_period, time_orientation, narrative_id, geo_scope, valid_from) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (sid, did, rel, epistemic, conf, es, ed, source_doc_id, e.get("mechanism"),
                 e.get("reference_period"), e.get("orientation"), narrative_id, _norm_geo(e.get("geo"))))
            rel_id = cur.lastrowid
            made += 1
        # 근거 이력 — 이 (엣지, 내러티브) 조합을 처음 본다면만 적재(멱등, 교차검증 카운트용).
        # 문서 레벨 추출은 내러티브가 아니므로 건너뜀 (source_doc_id로 별도 추적)
        if narrative_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO narrative_edge_evidence (entity_relation_id, narrative_id) VALUES (?, ?)",
                (rel_id, narrative_id))
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
# 효과 크기·방향 통제어휘 (확신=confidence와 분리된 축, D-065). float 금지=거짓 정밀(철학 §3).
EFFECT_STRENGTHS = {"unknown", "weak", "moderate", "strong"}  # 3단계+unknown (5단계는 모델 A/B 38% 불일치, D-066)
EFFECT_DIRECTIONS = {"positive", "negative", "mixed"}
# 인과 주장의 장소 스코프 통제어휘 (파편화 방지, D-034). 3개 프롬프트가 공유.
GEO_VOCAB = "한국|미국|중국|유럽|일본|대만|글로벌|기타"
_GEO_SET = set(GEO_VOCAB.split("|"))


def _norm_geo(v) -> str | None:
    """geo 값 정규화 — 통제어휘(GEO_VOCAB)에 없으면 None (거짓 정밀 방지)."""
    v = (v or "").strip()
    return v if v in _GEO_SET else None


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
    from pipeline.lenses import LENS_WORLDVIEW
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
        "{\"from\",\"to\",\"rel\",\"mechanism\",\"orientation\",\"reference_period\",\"geo\","
        "\"effect_direction\",\"effect_strength\",\"confidence\"}.\n"
        "  rel='CAUSES'(원인→결과). 수혜 섹터는 rel='BENEFITS_FROM'(from=수혜 섹터, to=체인 말단 동인).\n"
        "  앞의 끝(근본 원인)은 policy/regime/structure 노드까지 거슬러라. "
        "뒤의 끝(수혜)은 sector까지만 — 개별 종목 금지.\n"
        "  ★행위자: 인과의 뿌리나 중간에 특정 인물의 선언·비전·자본배분 결정(예: 젠슨 황의 로드맵 선언)이나 "
        "특정 기업의 결정·행동이 메커니즘의 실체라면 person/company 노드로 명시하라. "
        "판별 기준: '그 사람/기업이 사라지면 이 인과가 약해지는가' — 아니라면(단순 논평·스쳐가는 언급) 넣지 마라. "
        "company는 수혜 예측이 아니라 동인으로서만 (수혜 종착은 여전히 sector).\n"
        "  orientation ∈ past|current|forward (원인은 대개 past, 수혜 효과는 forward).\n"
        "  reference_period: 이 인과가 작동하는 시점(수집일 아님, 예 '2026 하반기'), 모르면 null.\n"
        f"  geo ∈ {{{GEO_VOCAB}}} 중 하나(특정 지역 사건이면 해당국, 전세계 공통이면 글로벌, 목록 밖이면 기타), 모르면 null.\n"
        "  effect_direction ∈ positive|negative|mixed (원인이 결과를 늘리나/줄이나).\n"
        "  effect_strength ∈ unknown|weak|moderate|strong (성립 시 효과의 크기 — 확신과 별개 축, 숫자 금지, 경계 애매하면 낮은 쪽).\n"
        "  confidence: 0~1 (이 인과 주장이 **참이라는 확신** — 효과 크기가 아니라 맞을 믿음). 원인→결과 방향만.\n"
        "  ★피드백(자기강화): 결과가 다시 원인을 강화하는 순환(예: AI 능력↑→합성 데이터→학습 강화→AI 능력↑)을 "
        "발견하면 버리지 말고 **시점이 다른 두 개의 엣지로 펴서** 표현하라 — A→B(reference_period=현재)와 "
        "B→A(reference_period=그 다음 시기, orientation=forward). 같은 시점 안에서의 순환(A→B→A 동시)은 금지. "
        "자기강화 루프는 가장 강력한 투자 구조이니 놓치지 마라.\n"
        f"\n{LENS_WORLDVIEW}\n"
        f"{kn}\n\n[수집된 문서 — '수집 날짜'는 발행일이지 사건 발생일이 아님. "
        f"대괄호 태그는 입력 주석일 뿐, 본문에 그대로 쓰지 말 것]\n{tl}"
    )


def _call(prompt: str, model: str = NARRATIVE_MODEL) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", model, "--output-format", "json", prompt],
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
        WHERE n.title IS NOT NULL AND COALESCE(n.kind,'topic')='topic'""").fetchall()
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


COVERAGE_MIN_DOCS = 30     # 커버리지 트리거 — 30일 문서 이만큼 이상이면 '꾸준히 두꺼운 주제'
COVERAGE_STALE_DAYS = 7    # 내러티브가 이보다 오래됐으면 재생성 후보
COVERAGE_PER_CYCLE = 2     # 사이클당 커버리지 생성 상한 (opus 비용 통제, 순환 소화)


def _coverage_topics(conn, exclude: set[str], limit: int = COVERAGE_PER_CYCLE) -> list[str]:
    """급증하진 않지만 문서가 꾸준히 두꺼운데 내러티브가 없거나 오래된 주제 (D-028 레버 2).
    theme_surge(급증)만 보면 반도체 725건 같은 상시 화두가 영원히 소외된다."""
    from pipeline.signals import THEME_STOPWORDS
    rows = conn.execute(f"""
        SELECT e.name, COUNT(DISTINCT rd.id) n
        FROM entity_links el JOIN entities e ON e.id=el.entity_id
        JOIN raw_documents rd ON rd.id=el.doc_id
        WHERE el.link_type IN ('industry','topic') AND e.type IN ('sector','theme')
          AND e.status IS NOT 'merged'
          AND rd.published_at >= datetime('now','-30 days')
        GROUP BY e.id HAVING n >= {COVERAGE_MIN_DOCS} ORDER BY n DESC
    """).fetchall()
    picked = []
    for r in rows:
        name = r["name"]
        if name in THEME_STOPWORDS or name in exclude:
            continue
        latest = conn.execute(
            "SELECT created_at FROM narratives WHERE topic=? ORDER BY version DESC LIMIT 1",
            (name,)).fetchone()
        fresh = latest and conn.execute(
            "SELECT datetime(?) >= datetime('now', ?)",
            (latest["created_at"], f"-{COVERAGE_STALE_DAYS} days")).fetchone()[0]
        if fresh:
            continue
        picked.append(name)
        if len(picked) >= limit:
            break
    return picked


def compute_top_narratives(limit: int = 5) -> dict:
    """cron 배치 — 사전 생성 트리거 2종 (멱등, hash 가드로 변경 시에만 opus).
    ① 급증: theme_surge 최신 신호 상위 N ② 커버리지: 문서 두꺼운데 내러티브 부재/오래됨 (D-028)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.name FROM signals s JOIN entities e ON e.id=s.entity_id
        WHERE s.signal_type='theme_surge'
          AND s.date=(SELECT MAX(date) FROM signals WHERE signal_type='theme_surge')
        ORDER BY json_extract(s.payload_json,'$.share_delta_pp') DESC LIMIT ?
    """, (limit,)).fetchall()
    topics = [r["name"] for r in rows]
    coverage = _coverage_topics(conn, exclude=set(topics))
    conn.close()
    results = {}
    for t in topics + coverage:
        try:
            results[t] = compute_narrative(t).get("status")
        except Exception as e:  # noqa: BLE001 — 배치라 한 주제 실패가 전체를 막지 않게
            results[t] = f"error:{str(e)[:80]}"
    return {"topics": topics, "coverage": coverage, "results": results}


def causal_subgraph(conn, narrative_id: int) -> dict:
    """한 내러티브의 인과 서브그래프 — 노드·엣지 (프론트 구조 뷰용).
    엣지마다 교차검증 정보(Phase 2 §2-4)도 얹는다: corroborated_by(이 엣지를 주장한 독립
    내러티브 수, narrative_edge_evidence 집계) · contested(반대 방향 CAUSES가 그래프에 공존)."""
    edges = conn.execute("""
        SELECT er.id, er.rel_type, er.mechanism, er.reference_period, er.time_orientation, er.confidence,
               er.effect_direction, er.effect_strength, er.obs_confirmed_at,
               er.promoted_knowledge_id, er.feedback_note, er.geo_scope, s.id sid, s.name sname, s.type stype, d.name dname, d.type dtype
        FROM entity_relations er
        JOIN entities s ON s.id=er.src_id JOIN entities d ON d.id=er.dst_id
        WHERE er.narrative_id=? AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
        ORDER BY er.id""", (narrative_id,)).fetchall()
    nodes: dict[int, dict] = {}
    out_edges = []
    for e in edges:
        nodes.setdefault(e["sid"], {"name": e["sname"], "type": e["stype"]})
        n_narratives = conn.execute(
            "SELECT COUNT(DISTINCT narrative_id) c FROM narrative_edge_evidence WHERE entity_relation_id=?",
            (e["id"],)).fetchone()["c"]
        # feedback_note가 있으면 opus가 '상충 아닌 시점 다른 피드백 나선'으로 해소한 것 → contested 제외(D-029)
        contested = e["rel_type"] == "CAUSES" and not e["feedback_note"] and conn.execute(
            "SELECT 1 FROM entity_relations er2 JOIN entities s2 ON s2.id=er2.src_id "
            "JOIN entities d2 ON d2.id=er2.dst_id WHERE er2.rel_type='CAUSES' AND s2.name=? AND d2.name=?",
            (e["dname"], e["sname"])).fetchone() is not None
        out_edges.append({"from": e["sname"], "from_type": e["stype"], "to": e["dname"],
                          "to_type": e["dtype"], "rel": e["rel_type"], "mechanism": e["mechanism"],
                          "orientation": e["time_orientation"], "reference_period": e["reference_period"],
                          "confidence": e["confidence"],
                          "effect_direction": e["effect_direction"], "effect_strength": e["effect_strength"],
                          "corroborated_by": n_narratives,
                          "contested": contested, "feedback_note": e["feedback_note"],
                          "geo_scope": e["geo_scope"], "obs_confirmed": bool(e["obs_confirmed_at"]),
                          "promoted_knowledge_id": e["promoted_knowledge_id"]})
    return {"nodes": list(nodes.values()), "edges": out_edges}


def narrative_grounding(conn, narrative_id: int) -> dict:
    """이 내러티브의 인과 엣지 중 지식으로 승격된 것들 + 각각의 미발화 반증 조건
    (Phase 2 §2-5, 지식→내러티브: 이 서사가 딛고 선 지식과 흔들릴 조건)."""
    rows = conn.execute("""
        SELECT DISTINCT k.id, k.statement, k.epistemic_status
        FROM entity_relations er JOIN knowledge k ON k.id = er.promoted_knowledge_id
        WHERE er.narrative_id=?""", (narrative_id,)).fetchall()
    items = []
    for r in rows:
        falsifiers = [f["condition"] for f in conn.execute(
            "SELECT condition FROM knowledge_falsifiers WHERE knowledge_id=? AND triggered_at IS NULL",
            (r["id"],)).fetchall()]
        items.append({"knowledge_id": r["id"], "statement": r["statement"],
                      "epistemic_status": r["epistemic_status"], "falsifiers": falsifiers})
    return {"status": "ok" if items else "empty", "grounding": items}


def related_narratives(conn, narrative_id: int) -> dict:
    """narrative_id와 인과 노드를 공유하는 다른 내러티브(주제별 최신 버전) — 공유 노드 수로
    랭킹 (Phase 2 §2-4 머지). 공유 노드 = 같은 그래프의 서브그래프라는 신호."""
    my_nodes = {n["name"] for n in causal_subgraph(conn, narrative_id)["nodes"]}
    if not my_nodes:
        return {"status": "empty", "related": []}
    rows = conn.execute("""
        SELECT n.id, n.topic, n.title FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives GROUP BY topic) l
          ON l.topic = n.topic AND l.mv = n.version
        WHERE n.id != ? AND COALESCE(n.kind,'topic')='topic'""", (narrative_id,)).fetchall()
    related = []
    for row in rows:
        other_nodes = {n["name"] for n in causal_subgraph(conn, row["id"])["nodes"]}
        shared = my_nodes & other_nodes
        if shared:
            related.append({"narrative_id": row["id"], "topic": row["topic"], "title": row["title"],
                             "shared_nodes": sorted(shared)})
    related.sort(key=lambda r: -len(r["shared_nodes"]))
    return {"status": "ok" if related else "empty", "related": related}


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


def _edge_key(e: dict) -> tuple:
    return (e["from"], e["to"], e["rel"])


def _version_diff(conn, narrative_id: int) -> dict:
    """narrative_id 버전과 직전 버전(topic, version-1)의 인과 서브그래프 비교 (Phase 2 §2-3).
    엣지는 (from,to,rel) 노드-이름 정체성으로 비교한다 — 재적재 시 narrative_id 태그가
    최신 버전으로 옮겨가므로(D-023 confidence 강화), 태그가 아니라 정체성으로 비교해야
    '그대로 이어진 고리'를 '사라짐+새로 생김'으로 오판하지 않는다."""
    cur = conn.execute("SELECT topic, version FROM narratives WHERE id=?", (narrative_id,)).fetchone()
    if not cur:
        return {"status": "not_found"}
    prev_row = conn.execute(
        "SELECT id FROM narratives WHERE topic=? AND version=?",
        (cur["topic"], cur["version"] - 1)).fetchone()
    if not prev_row:
        return {"status": "no_prior_version"}
    cur_graph = causal_subgraph(conn, narrative_id)
    prev_graph = causal_subgraph(conn, prev_row["id"])
    cur_edges = {_edge_key(e): e for e in cur_graph["edges"]}
    prev_edges = {_edge_key(e): e for e in prev_graph["edges"]}
    cur_nodes = {n["name"] for n in cur_graph["nodes"]}
    prev_nodes = {n["name"] for n in prev_graph["nodes"]}
    return {
        "status": "ok", "prev_version_id": prev_row["id"],
        "added_nodes": sorted(cur_nodes - prev_nodes),
        "removed_nodes": sorted(prev_nodes - cur_nodes),
        "added_edges": [cur_edges[k] for k in cur_edges.keys() - prev_edges.keys()],
        "removed_edges": [prev_edges[k] for k in prev_edges.keys() - cur_edges.keys()],
    }


def _build_drift_prompt(added_edges: list[dict], removed_edges: list[dict]) -> str:
    def fmt(es):
        return "\n".join(f"- {e['from']} → {e['to']} ({e['rel']})" for e in es) or "(없음)"
    return (
        "아래는 한 내러티브의 인과 그래프가 이전 버전 대비 어떻게 바뀌었는지다. "
        "핵심 고리가 어디서 어디로 이동했는지 한국어 한 문장으로 요약해라"
        "(예: '유가→금리 고리가 빠지고 반도체→AI 고리가 새로 들어왔다').\n"
        f"새로 생긴 고리:\n{fmt(added_edges)}\n\n사라진 고리:\n{fmt(removed_edges)}\n\n"
        'JSON만 출력: {"summary": "..."}'
    )


def narrative_diff(conn, narrative_id: int) -> dict:
    """버전 드리프트 — 결정적 diff(LLM 없음) + 변화가 있으면 게으른 haiku 한 줄 요약(캐시)."""
    d = _version_diff(conn, narrative_id)
    if d["status"] != "ok":
        return d
    if not d["added_edges"] and not d["removed_edges"]:
        d["summary"] = None
        return d
    row = conn.execute("SELECT drift_summary FROM narratives WHERE id=?", (narrative_id,)).fetchone()
    if row and row["drift_summary"]:
        d["summary"] = row["drift_summary"]
        return d
    if llm_engine() != "claude-code":
        d["summary"] = None
        return d
    try:
        data = _call(_build_drift_prompt(d["added_edges"], d["removed_edges"]), model="haiku")
    except Exception:
        d["summary"] = None
        return d
    d["summary"] = data.get("summary")
    conn.execute("UPDATE narratives SET drift_summary=? WHERE id=?", (d["summary"], narrative_id))
    conn.commit()
    return d


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

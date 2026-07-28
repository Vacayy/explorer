"""논지 감사 (thesis audit, docs/specs/thesis-audit.md) — 내 thesis를 축적된 인과그래프에 대질.

**read-only 감사**(등재 아님). 산출 = 델타: 각 주장이 그래프와 일치/충돌/신규/선반영인가.
moat는 추론이 아니라 정박 — 모든 판정이 코퍼스 포인터(엣지 id·독립 소스 수·created_at·내러티브 버전)를 가리킨다.

Phase 1(본 모듈): **정박 코어(stage 2, 결정적·LLM 0)** — 주장의 앵커 엔티티를 해소하고
매칭 인과 엣지(교차검증·방향·시점)·내러티브·시간 급증을 조회해 주장별 판정. LLM 분해(stage 1)·
종합(stage 5)·진자(stage 3)·반증/프록시(stage 4)는 후속 Phase에서 이 코어 위에 배선.
"""
from database import get_connection
from pipeline.enrich import _call_claude_code, _parse_json

_CAUSAL = ("CAUSES", "BENEFITS_FROM")
_ANCHOR_TYPES = ("sector", "theme", "company", "macro", "industry", "event", "policy")


def _resolve_entities(conn, terms: list[str], limit: int = 8) -> list[dict]:
    """앵커 용어 → 매칭 엔티티(언급량 순). Phase 1은 이름 매칭(의미검색은 Phase 2)."""
    if not terms:
        return []
    like = " OR ".join(["e.name LIKE ?"] * len(terms))
    types = ",".join(f"'{t}'" for t in _ANCHOR_TYPES)
    rows = conn.execute(
        f"SELECT e.id, e.name, e.type, COUNT(l.doc_id) mentions "
        f"FROM entities e JOIN entity_links l ON l.entity_id=e.id "
        f"WHERE ({like}) AND e.type IN ({types}) "
        f"GROUP BY e.id ORDER BY mentions DESC LIMIT ?",
        [f"%{t}%" for t in terms] + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def _edges_for(conn, entity_ids: list[int], limit: int = 12) -> list[dict]:
    """앵커 엔티티를 잇는 인과 엣지 + 교차검증(독립 내러티브 수)·방향·강도·시점."""
    if not entity_ids:
        return []
    idlist = ",".join(str(i) for i in entity_ids)
    rows = conn.execute(
        f"SELECT r.id, r.src_id, r.dst_id, r.rel_type, r.epistemic_type, r.confidence, "
        f"  r.effect_direction, r.effect_strength, r.mechanism, r.created_at, r.reference_period, "
        f"  (SELECT COUNT(DISTINCT narrative_id) FROM narrative_edge_evidence WHERE entity_relation_id=r.id) corrob "
        f"FROM entity_relations r "
        f"WHERE (r.src_id IN ({idlist}) OR r.dst_id IN ({idlist})) AND r.rel_type IN {_CAUSAL} "
        f"ORDER BY corrob DESC, r.confidence DESC LIMIT ?",
        (limit,),
    ).fetchall()
    name = {r["id"]: r["name"] for r in conn.execute(
        f"SELECT id, name FROM entities WHERE id IN ("
        f"  SELECT src_id FROM entity_relations WHERE id IN ({','.join(str(e['id']) for e in rows)}) "
        f"  UNION SELECT dst_id FROM entity_relations WHERE id IN ({','.join(str(e['id']) for e in rows)}))"
    ).fetchall()} if rows else {}
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "src": name.get(r["src_id"], r["src_id"]), "dst": name.get(r["dst_id"], r["dst_id"]),
            "rel_type": r["rel_type"], "epistemic_type": r["epistemic_type"], "confidence": r["confidence"],
            "effect_direction": r["effect_direction"], "effect_strength": r["effect_strength"],
            "corroborated_by": r["corrob"], "mechanism": r["mechanism"],
            "created_at": r["created_at"], "reference_period": r["reference_period"],
        })
    return out


def _narratives_for(conn, terms: list[str], limit: int = 5) -> list[dict]:
    """주장을 다루는 내러티브(+버전·드리프트)."""
    if not terms:
        return []
    like = " OR ".join(["topic LIKE ? OR title LIKE ?"] * len(terms))
    args = []
    for t in terms:
        args += [f"%{t}%", f"%{t}%"]
    rows = conn.execute(
        f"SELECT topic, version, title, category, drift_summary, created_at FROM narratives "
        f"WHERE kind='topic' AND superseded_at IS NULL AND ({like}) "
        f"ORDER BY version DESC, created_at DESC LIMIT ?",
        args + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def _temporal(conn, terms: list[str], since: str = "2025-01", months: int = 8) -> dict:
    """주장 개념의 월별 문서수 → 최근 급증(spike) 감지 = '최근 본격화' 검증. 결정적."""
    if not terms:
        return {"monthly": [], "spiking": False}
    like = " OR ".join(["markdown LIKE ?"] * len(terms))
    rows = conn.execute(
        f"SELECT substr(published_at,1,7) ym, COUNT(*) c FROM raw_documents "
        f"WHERE ({like}) AND published_at >= ? GROUP BY ym ORDER BY ym DESC LIMIT ?",
        [f"%{t}%" for t in terms] + [since, months],
    ).fetchall()
    monthly = [{"ym": r["ym"], "count": r["c"]} for r in rows]
    # 급증: 최신월이 직전월의 3배 이상 & 최신월 ≥ 10
    spiking = False
    if len(monthly) >= 2 and monthly[0]["count"] >= 10 and monthly[1]["count"] > 0:
        spiking = monthly[0]["count"] / monthly[1]["count"] >= 3
    return {"monthly": monthly, "spiking": spiking, "latest": monthly[0] if monthly else None,
            "prev": monthly[1] if len(monthly) > 1 else None}


def ground_claim(claim: str, anchor_terms: list[str]) -> dict:
    """한 주장의 **후보** 근거를 그래프에서 검색 (stage 2 후보검색, LLM 0).

    이름매칭이라 엔티티 이웃 전체를 긁는다 — 주장-특정 필터는 filter_edges(stage 2 정밀)가 담당.
    """
    conn = get_connection()
    ents = _resolve_entities(conn, anchor_terms)
    edges = _edges_for(conn, [e["id"] for e in ents])
    narrs = _narratives_for(conn, anchor_terms)
    temporal = _temporal(conn, anchor_terms)
    conn.close()
    return {"claim": claim, "anchor_terms": anchor_terms,
            "entities": ents, "edges": edges, "narratives": narrs, "temporal": temporal}


# ──────────────────── Phase 2: LLM 분해 + 엣지 관련성 필터 (stage 1·2 정밀) ────────────────────

def _graph_vocab(limit: int = 70) -> list[str]:
    """그래프에 실제 존재하는 앵커 노드 이름 (언급 많은 순) — 앵커 해소율 위해 프롬프트 주입."""
    conn = get_connection()
    types = ",".join(f"'{t}'" for t in _ANCHOR_TYPES)
    rows = conn.execute(
        f"SELECT e.name FROM entities e JOIN entity_links l ON l.entity_id=e.id "
        f"WHERE e.type IN ({types}) GROUP BY e.id ORDER BY COUNT(l.doc_id) DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def decompose_thesis(text: str, model: str = "sonnet") -> list[dict]:
    """자유서술 thesis → 원자 주장 + 역할 + 정밀 앵커 (stage 1).

    앵커는 **그래프 기존 노드에서 우선 선택**(enrich 패턴) — 안 그러면 LLM이 그럴듯하나 안 맞는
    이름을 지어내 정박이 0이 된다(실측: 'GPU'·'컴퓨팅 자본' 미해소).
    """
    vocab = _graph_vocab()
    prompt = (
        "다음 투자 논지를 원자 주장으로 분해해 JSON만 출력해. 설명·코드블록·명령 실행 금지.\n"
        '형식: {"claims": [{"claim": "한 문장 주장", '
        '"role": "consensus|shift|catalyst|causal|synthesis", '
        '"anchor_terms": ["구체 명사"]}]}\n'
        "규칙:\n"
        "- role: consensus(글쓴이가 '대부분 동의'라 표시) · shift(새로 흔들리는 관측) · "
        "catalyst(촉매 사건) · causal(A→B 인과) · synthesis(전체 종합)\n"
        "- anchor_terms: **아래 '그래프 노드' 목록에서 이 주장과 관련된 이름을 우선 선택**. "
        "목록에 정확히 없으면 가장 가까운 이름을 쓰되, 정 없으면 구체 명사 신규 허용. 'AI' 단독 금지.\n"
        f"- 그래프 노드: {', '.join(vocab)}\n"
        f"논지:\n{text}"
    )
    data = _parse_json(_call_claude_code(prompt, model=model, timeout=180))
    out = []
    for c in data.get("claims", []):
        if c.get("claim"):
            out.append({"claim": c["claim"].strip(),
                        "role": (c.get("role") or "causal").strip(),
                        "anchor_terms": [t.strip() for t in (c.get("anchor_terms") or []) if t.strip()]})
    return out


def filter_edges(claim: str, edges: list[dict], model: str = "haiku") -> dict[int, str]:
    """후보 엣지 중 이 주장과 관련된 것 + 입장(support/contradict/context). {edge_id: stance}."""
    if not edges:
        return {}
    cand = "\n".join(
        f'{{"id": {e["id"]}, "edge": "{e["src"]}→{e["dst"]}", "dir": "{e["effect_direction"] or "?"}", '
        f'"mechanism": "{(e["mechanism"] or "")[:80]}"}}' for e in edges)
    prompt = (
        "다음 주장과 각 인과 엣지의 관계를 판정해 JSON만 출력해. 설명·코드블록·명령 실행 금지.\n"
        f'주장: "{claim}"\n'
        '형식: {"edges": [{"id": 정수, "stance": "support|contradict|context"}]}\n'
        "규칙: 주장을 뒷받침=support, 반박=contradict, 배경설명=context, 무관하면 목록에서 제외.\n"
        f"엣지:\n{cand}"
    )
    data = _parse_json(_call_claude_code(prompt, model=model, timeout=120))
    return {e["id"]: e.get("stance", "context") for e in data.get("edges", [])
            if isinstance(e.get("id"), int) and e.get("stance") in ("support", "contradict", "context")}


def audit_thesis(text: str) -> dict:
    """논지 감사 end-to-end (stage 1·2). read-only. 산출 = 주장별 델타 + 정밀 근거."""
    claims = decompose_thesis(text)
    results = []
    for c in claims:
        g = ground_claim(c["claim"], c["anchor_terms"])
        stances = filter_edges(c["claim"], g["edges"])          # LLM 관련성 필터
        rel = [{**e, "stance": stances[e["id"]]} for e in g["edges"] if e["id"] in stances]
        supports = [e for e in rel if e["stance"] == "support"]
        contradicts = [e for e in rel if e["stance"] == "contradict"]
        # 정밀 판정 — 이웃 전체가 아니라 주장-관련 엣지로만
        if not rel and not g["narratives"]:
            verdict = "novel"           # 그래프에 없음
        elif supports and contradicts:
            verdict = "contested"       # 축적된 반례 공존
        elif contradicts:
            verdict = "challenged"      # 그래프가 반박
        else:
            verdict = "aligned"         # 그래프가 지지
        results.append({
            "claim": c["claim"], "role": c["role"], "anchor_terms": c["anchor_terms"],
            "verdict": verdict, "spiking": g["temporal"]["spiking"],
            "edges": rel, "narratives": g["narratives"], "temporal": g["temporal"],
        })
    return {"claims": results, "n_claims": len(results)}

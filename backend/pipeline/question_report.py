"""질문 종합 (D-093) — 서브질문·판정·온톨로지 근거로 '현재 결산 리포트'를 뽑고,
그 리포트를 출발 조건으로 파급 시나리오를 체인 생성한다.

- 리포트 = 근거 정박 *현재 결산*(2층 판정·프록시 관측·딛고 선 지식이 말하는 것, 미판정은 정직히 미판정).
  종합이나 재료가 이미 구조화돼 있어 **sonnet**(리포트 엔진 opus 재사용 안 함 — 가벼운 결산).
- 시나리오 = 기존 opus 엔진(scenario.build_scenario)에 리포트를 report_context로 주입 → *전방 전망*.
- 체인: 리포트(현재) → 시나리오(전방). append-only 리포트 + inputs_hash 캐시 가드
  (재료 안 바뀌면 재열람 공짜, 리포트 갱신 시에만 시나리오 재생성 — 비용 체인).
- 에피스테믹 분리(비타협): 리포트는 미판정을 미판정으로, 시나리오는 그 위의 가정형 전망.
"""
import hashlib
import json

from database import get_connection
from pipeline.enrich import _call_claude_code, llm_available

REPORT_MODEL = "sonnet"
_KO = {"leaning_yes": "긍정 우세", "leaning_no": "부정 우세", "mixed": "혼조", "unknown": "미판정"}
_DIV_KO = {"aligned": "선행·확정 정합", "lead_ahead": "선행이 확정보다 앞섬(여론 선반영 의심)",
           "confirm_ahead": "확정이 선행보다 앞섬(실적이 여론을 끌어당김)"}


def _gather(conn, question_id: int) -> dict | None:
    """리포트 재료 — 판정·서브질문·프록시 관측·딛고 선 지식 (LLM 0)."""
    q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if not q:
        return None
    subs = []
    for sq in conn.execute(
            "SELECT id, text, verdict FROM sub_questions WHERE question_id=? ORDER BY id", (question_id,)).fetchall():
        proxies = []
        for p in conn.execute(
                "SELECT id, label, modality, yes_direction, unit FROM proxy_registry "
                "WHERE sub_question_id=? AND active=1 ORDER BY id", (sq["id"],)).fetchall():
            obs = conn.execute(
                "SELECT observed_at, value_num, value_text, direction FROM proxy_observations "
                "WHERE proxy_id=? ORDER BY observed_at DESC, id DESC LIMIT 1", (p["id"],)).fetchone()
            proxies.append({"label": p["label"], "modality": p["modality"], "unit": p["unit"],
                            "obs": dict(obs) if obs else None})
        subs.append({"text": sq["text"], "verdict": sq["verdict"], "proxies": proxies})
    grounding = []
    if q["narrative_id"]:
        from pipeline.narrative import narrative_grounding
        grounding = narrative_grounding(conn, q["narrative_id"]).get("grounding", [])
    return {"q": dict(q), "subs": subs, "grounding": grounding}


def _hash(ev: dict) -> str:
    """느리게 변하는 재료만 — 판정·서브질문 verdict·프록시 최신 관측 방향·근거 지식 id."""
    q = ev["q"]
    parts = [f"v:{q['lead_verdict']}:{q['confirm_verdict']}:{q['divergence']}"]
    for s in ev["subs"]:
        parts.append(f"sq:{s['text'][:20]}:{s['verdict']}")
        for p in s["proxies"]:
            d = (p["obs"] or {}).get("direction")
            v = (p["obs"] or {}).get("value_num")
            parts.append(f"px:{p['label'][:16]}:{d}:{v}")
    parts += [f"kn:{g['knowledge_id']}" for g in ev["grounding"]]
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _has_material(ev: dict) -> bool:
    return bool(ev["subs"])  # 서브질문이 있어야 결산할 게 있다


def _build_report_prompt(ev: dict) -> str:
    q = ev["q"]
    lines = [f"[핵심 질문] {q['text']}",
             f"[선행 판정 — 여론·태세] {_KO.get(q['lead_verdict'], '미판정')}",
             f"[확정 판정 — 수치 실적] {_KO.get(q['confirm_verdict'], '미판정')}",
             f"[선행 vs 확정] {_DIV_KO.get(q['divergence'] or '', '—')}"]
    for i, s in enumerate(ev["subs"], 1):
        lines.append(f"\n[서브질문 {i}] {s['text']} — 판정: {_KO.get(s['verdict'], '미판정')}")
        for p in s["proxies"]:
            o = p["obs"]
            if o:
                val = o.get("value_text") or (f"{o['value_num']}{p['unit'] or ''}" if o.get("value_num") is not None else "")
                lines.append(f"  · 프록시 {p['label']}: 최근 관측 {o.get('direction') or '?'} {val} ({(o.get('observed_at') or '')[:10]})")
            else:
                lines.append(f"  · 프록시 {p['label']}: 관측 없음(미판정)")
    if ev["grounding"]:
        lines.append("\n[이 질문이 딛고 선 검증 지식 + 흔들릴 조건]")
        for g in ev["grounding"]:
            fal = "; ".join(g["falsifiers"][:2]) if g["falsifiers"] else "반증조건 없음"
            lines.append(f"  · {g['statement']} (반증: {fal})")
    return (
        "너는 핵심 질문을 추적해온 리서치 애널리스트다. 아래 추적 상태(판정·프록시 관측·딛고 선 지식)만 근거로, "
        "**지금 시점에 이 질문에 대해 말할 수 있는 것**을 짧은 결산 리포트로 종합해라. 재료 나열이 아니라 판단이다.\n"
        "규율:\n"
        "- 예측이 아니라 **현재 결산**이다. 아직 관측이 없는 부분은 반드시 '미판정'이라고 정직하게 말한다(꾸며내지 말 것).\n"
        "- 선행(여론)과 확정(실적)이 갈리면 그 괴리가 무슨 뜻인지 짚어라.\n"
        "- 딛고 선 지식이 있으면 그게 이 결산의 전제이고, 무엇이 그걸 흔들 수 있는지 명시.\n"
        "- 내부코드·약어(leaning_yes 등) 노출 금지, 자연어로.\n\n"
        + "\n".join(lines) + "\n\n"
        'JSON만 출력: {"report": "마크다운 결산. 구조: 첫 문단 종합 2~3문장(지금 답할 수 있는 것) + '
        '### 확인된 것 / ### 아직 미판정 / ### 딛고 선 전제와 흔들릴 조건(근거 지식 있을 때만)"}'
    )


def _generate_report(ev: dict) -> str | None:
    prompt = _build_report_prompt(ev)
    try:
        out = _call_claude_code(prompt, model=REPORT_MODEL, timeout=240)
    except Exception:  # noqa: BLE001
        return None
    s, e = out.find("{"), out.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return (json.loads(out[s:e + 1]).get("report") or "").strip() or None
    except Exception:  # noqa: BLE001
        return None


def _latest_report(conn, question_id: int):
    return conn.execute(
        "SELECT body, inputs_hash, created_at FROM question_reports WHERE question_id=? ORDER BY id DESC LIMIT 1",
        (question_id,)).fetchone()


def synthesis_status(question_id: int) -> dict:
    """LLM 0 — 캐시된 리포트 + stale 플래그. 시나리오는 get_tree가 이미 반환하므로 여기선 리포트만."""
    conn = get_connection()
    ev = _gather(conn, question_id)
    if not ev:
        conn.close()
        return {"status": "not_found"}
    if not _has_material(ev):
        conn.close()
        return {"status": "empty", "body": None, "created_at": None, "stale": False}
    cached = _latest_report(conn, question_id)
    h = _hash(ev)
    conn.close()
    if not cached:
        return {"status": "empty", "body": None, "created_at": None, "stale": True}
    return {"status": "ok", "body": cached["body"], "created_at": cached["created_at"],
            "stale": cached["inputs_hash"] != h}


def compute_synthesis(question_id: int, refresh: bool = False) -> dict:
    """리포트(현재 결산, sonnet) → 그걸 출발 조건으로 파급 시나리오(전방, opus) 체인.

    캐시 체인: 리포트 재료(inputs_hash) 안 바뀌고 refresh 아니면 리포트 재사용 + 시나리오도 유지.
    리포트가 새로 생성될 때만(재료 변화·refresh) 시나리오도 재생성(비용 체인).
    """
    if not llm_available():
        return {"status": "unavailable"}
    conn = get_connection()
    ev = _gather(conn, question_id)
    if not ev:
        conn.close()
        return {"status": "not_found"}
    if not _has_material(ev):
        conn.close()
        return {"status": "empty"}
    h = _hash(ev)
    cached = _latest_report(conn, question_id)
    conn.close()

    report_fresh = False
    if cached and cached["inputs_hash"] == h and not refresh:
        body = cached["body"]
    else:
        body = _generate_report(ev)
        if not body:
            return {"status": "failed"}
        conn = get_connection()
        conn.execute(
            "INSERT INTO question_reports (question_id, body, inputs_hash, model) VALUES (?,?,?,?)",
            (question_id, body, h, f"claude-code/{REPORT_MODEL}"))
        conn.commit()
        conn.close()
        report_fresh = True

    # 체인: 리포트를 출발 조건으로 시나리오 (리포트 새로 생겼거나 refresh거나 시나리오 부재일 때만)
    from pipeline.questions import run_scenario_for_event
    conn = get_connection()
    has_scenario = conn.execute(
        "SELECT 1 FROM scenarios WHERE question_id=?", (question_id,)).fetchone() is not None
    conn.close()
    scenario = None
    if report_fresh or refresh or not has_scenario:
        r = run_scenario_for_event(ev["q"]["text"], question_id=question_id, report_context=body)
        if not r.get("error"):
            scenario = {"answer": r.get("answer"), "beneficiaries": r.get("beneficiaries") or []}

    created = _fresh_created(question_id)
    return {"status": "ok", "report": {"body": body, "created_at": created}, "scenario": scenario}


def _fresh_created(question_id: int) -> str | None:
    conn = get_connection()
    row = _latest_report(conn, question_id)
    conn.close()
    return row["created_at"] if row else None

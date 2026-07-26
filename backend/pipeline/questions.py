"""핵심질문 트래커 (D-067·D-068, docs/specs/question-proxy.md).

분할정복: 핵심질문 → 서브질문(반증조건 보유) → 프록시(관측 대상) → 관측 → 판정.
- decompose_question: 질문을 LLM(sonnet)이 서브질문·프록시로 분해 → 적재 → numeric 프록시 추출 트리거.
- rollup: 프록시 관측을 pace layer 2층(선행 fast / 확정 slow)으로 결정적 롤업 + 게으른 LLM 한 줄 종합.
- get_tree / list_questions: 조회.

판정은 하이브리드 — 결정적 스코어(LLM 0)가 verdict를 정하고, 서술(verdict_summary)만 판정이 바뀔 때 haiku.
관측 추출·판정은 event-driven(관측 갱신 편승, 재료 없으면 no-op) — 고정 폴러 없음.
"""
import json

from database import get_connection

_FAST = ("sentiment", "stance")


_DECOMPOSE_PROMPT = """당신은 투자 리서치 애널리스트다. 아래 '핵심 질문'을 **분할정복**으로 쪼갠다.
이 질문에 답하려면 투자자가 무엇을 관측해야 하는가를 3~6개의 **서브질문**으로 나누고,
각 서브질문마다 **관측 프록시**(추적할 지표/신호)를 붙여라.

[핵심 질문] {question}

규칙:
- 서브질문은 핵심 질문의 논리적 성분이어야 한다(투입·수요·전환·마진·밸류·심리 등 다른 축).
- 각 서브질문에 `falsifier`(반증조건: "이 방향으로 관측되면 핵심 질문이 틀린 것")를 명시.
- 프록시 `modality` 3종:
  · numeric  — 실적 컨콜/재무의 수치(CAPEX·ARR·매출성장률·영업이익률·FCF 등). 관련 미국 티커(`tickers`)와
    추출 힌트(`extract_hint`) 필수. 이 값은 실적 컨콜 전문에서 추출된다.
  · sentiment — 투자자 여론(텔레그램·블로그·유튜브 화두). tickers 불필요.
  · stance    — 경영진·수장의 발언 태세 변화(보수적으로 돌아서나). tickers 불필요.
- `yes_direction`: 어느 관측 방향(up/down)이 **핵심 질문 '예'의 근거**인가. 예: "CAPEX가 늘어나는가?"면 up,
  "마진이 축소되나?"가 핵심질문 부정 근거면 그 프록시의 yes_direction은 down.

JSON만 출력:
{{"sub_questions": [
  {{"text": "서브질문", "falsifier": "반증조건 한 문장",
    "proxies": [
      {{"label": "프록시 이름", "modality": "numeric|sentiment|stance",
        "tickers": "MSFT,GOOGL" 또는 "", "unit": "$B|%|..." 또는 "",
        "extract_hint": "컨콜에서 무엇을 볼지(numeric만)", "yes_direction": "up|down"}}
    ]}}
]}}"""


def _slugify(label: str, qid: int, i: int) -> str:
    base = "".join(c if c.isalnum() else "_" for c in (label or "proxy").lower())[:32]
    return f"q{qid}_{base}_{i}"


def decompose_question(text: str, created_by: str = "user",
                       narrative_id: int | None = None, source_doc_id: int | None = None) -> dict:
    """질문을 서브질문·프록시로 분해해 적재하고 numeric 프록시 관측을 추출한 뒤 트리를 반환한다."""
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return {"error": "llm 미가용"}
    try:
        raw = _call_claude_code(_DECOMPOSE_PROMPT.format(question=text), model="sonnet", timeout=240)
        plan = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception as e:  # noqa: BLE001
        return {"error": f"분해 실패: {e}"}

    conn = get_connection()
    status = "proposed" if created_by == "system" else "tracking"
    cur = conn.execute(
        "INSERT INTO questions (text, narrative_id, source_doc_id, created_by, status) VALUES (?, ?, ?, ?, ?)",
        (text.strip(), narrative_id, source_doc_id, created_by, status))
    qid = cur.lastrowid
    has_numeric = False
    for sq in plan.get("sub_questions", []):
        scur = conn.execute(
            "INSERT INTO sub_questions (question_id, text, falsifier) VALUES (?, ?, ?)",
            (qid, (sq.get("text") or "").strip(), (sq.get("falsifier") or "").strip() or None))
        sqid = scur.lastrowid
        for i, p in enumerate(sq.get("proxies", [])):
            modality = p.get("modality") if p.get("modality") in ("numeric", "sentiment", "stance") else "numeric"
            yes_dir = p.get("yes_direction") if p.get("yes_direction") in ("up", "down") else "up"
            conn.execute(
                "INSERT OR IGNORE INTO proxy_registry "
                "(key, label, sub_question_id, modality, tickers, unit, extract_hint, yes_direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_slugify(p.get("label", ""), qid, i), (p.get("label") or "프록시").strip(), sqid, modality,
                 (p.get("tickers") or "").strip() or None, (p.get("unit") or "").strip() or None,
                 (p.get("extract_hint") or "").strip() or None, yes_dir))
            if modality == "numeric" and (p.get("tickers") or "").strip():
                has_numeric = True
    conn.commit()
    conn.close()

    # numeric 프록시는 컨콜에서 즉시 추출(event-driven 편승 — 여기선 최초 분해 시 1회). sentiment/stance는 Phase 2.
    if has_numeric:
        try:
            from pipeline.transcript import extract_proxies
            extract_proxies(limit=40)
        except Exception as e:  # noqa: BLE001
            print(f"[question] 프록시 추출 실패: {e}")

    rollup(qid)
    return get_tree(qid)


def _verdict(score: int, n: int) -> str:
    if n == 0:
        return "unknown"
    ratio = score / n
    if ratio >= 0.34:
        return "leaning_yes"
    if ratio <= -0.34:
        return "leaning_no"
    return "mixed"


_SIGN = {"leaning_yes": 1, "leaning_no": -1, "mixed": 0, "unknown": None}


def _divergence(lead: str, confirm: str) -> str:
    a, b = _SIGN.get(lead), _SIGN.get(confirm)
    if a is None or b is None or a == b:
        return "aligned"
    return "lead_ahead" if a > b else "confirm_ahead"


def rollup(question_id: int) -> dict:
    """프록시 관측을 pace layer 2층으로 결정적 롤업. 판정이 바뀌면 haiku 한 줄 종합(게으르게)."""
    conn = get_connection()
    q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if not q:
        conn.close()
        return {"error": "질문 없음"}
    subs = conn.execute("SELECT * FROM sub_questions WHERE question_id=?", (question_id,)).fetchall()
    lead, confirm = [], []
    for sq in subs:
        proxies = conn.execute(
            "SELECT id, modality, yes_direction FROM proxy_registry WHERE sub_question_id=? AND active=1",
            (sq["id"],)).fetchall()
        sq_scores = []
        for p in proxies:
            obs = conn.execute(
                "SELECT direction FROM proxy_observations WHERE proxy_id=? AND direction IS NOT NULL "
                "ORDER BY observed_at DESC, id DESC LIMIT 1", (p["id"],)).fetchone()
            if not obs:
                continue
            d = obs["direction"]
            yd = p["yes_direction"] or "up"
            s = 0 if d == "flat" else (1 if d == yd else -1)
            sq_scores.append(s)
            (lead if p["modality"] in _FAST else confirm).append(s)
        sv = _verdict(sum(sq_scores), len(sq_scores))
        conn.execute("UPDATE sub_questions SET verdict=? WHERE id=?", (sv, sq["id"]))

    lead_v = _verdict(sum(lead), len(lead))
    confirm_v = _verdict(sum(confirm), len(confirm))
    div = _divergence(lead_v, confirm_v)

    changed = (lead_v, confirm_v, div) != (q["lead_verdict"], q["confirm_verdict"], q["divergence"])
    summary = q["verdict_summary"]
    if changed:
        summary = _summarize(conn, q, lead_v, confirm_v, div)
    conviction = (abs(sum(confirm)) / len(confirm)) if confirm else None
    conn.execute(
        "UPDATE questions SET lead_verdict=?, confirm_verdict=?, divergence=?, verdict_summary=?, "
        "conviction=?, updated_at=datetime('now') WHERE id=?",
        (lead_v, confirm_v, div, summary, conviction, question_id))
    conn.commit()
    conn.close()
    return {"lead_verdict": lead_v, "confirm_verdict": confirm_v, "divergence": div, "changed": changed}


_SUMMARY_PROMPT = """핵심 질문의 현재 판정을 한국어 한 문장으로 종합하라(간결히, 내부코드·약어 노출 금지).
[핵심 질문] {q}
[선행 판정 — 여론·태세(fast)] {lead}
[확정 판정 — 수치 실적(slow)] {confirm}
[서브질문별 판정] {subs}
아직 관측이 없는 부분(unknown)은 "미판정"으로 정직히 말하라. 한 문장만 출력."""

_KO = {"leaning_yes": "긍정", "leaning_no": "부정", "mixed": "혼조", "unknown": "미판정"}


def _summarize(conn, q, lead_v, confirm_v, div) -> str | None:
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return None
    subs = conn.execute("SELECT text, verdict FROM sub_questions WHERE question_id=?", (q["id"],)).fetchall()
    sub_txt = " / ".join(f"{s['text']}: {_KO.get(s['verdict'], '미판정')}" for s in subs)
    try:
        out = _call_claude_code(
            _SUMMARY_PROMPT.format(q=q["text"], lead=_KO.get(lead_v), confirm=_KO.get(confirm_v), subs=sub_txt),
            model="haiku", timeout=120)
        return out.strip().split("\n")[0][:400] or None
    except Exception:  # noqa: BLE001
        return None


def get_tree(question_id: int) -> dict:
    conn = get_connection()
    q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if not q:
        conn.close()
        return {"error": "질문 없음"}
    tree = dict(q)
    subs = []
    for sq in conn.execute("SELECT * FROM sub_questions WHERE question_id=? ORDER BY id", (question_id,)).fetchall():
        proxies = []
        for p in conn.execute(
                "SELECT * FROM proxy_registry WHERE sub_question_id=? ORDER BY id", (sq["id"],)).fetchall():
            obs = [dict(o) for o in conn.execute(
                "SELECT observed_at, value_num, value_text, direction FROM proxy_observations "
                "WHERE proxy_id=? ORDER BY observed_at DESC, id DESC LIMIT 6", (p["id"],)).fetchall()]
            proxies.append({**dict(p), "observations": obs})
        subs.append({**dict(sq), "proxies": proxies})
    tree["sub_questions"] = subs
    conn.close()
    return tree


def list_questions() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT q.*, (SELECT COUNT(*) FROM sub_questions sq WHERE sq.question_id=q.id) AS sub_count "
        "FROM questions q WHERE status != 'dismissed' ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dismiss_question(question_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE questions SET status='dismissed' WHERE id=?", (question_id,))
    conn.commit()
    conn.close()

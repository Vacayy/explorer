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
- 서브질문은 핵심 질문의 논리적 성분이어야 한다(투입·수요·공급·전환·마진·밸류·심리 등 다른 축).
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
    """새 질문을 적재하고 즉시 서브질문·프록시로 분해·추출·판정 (생성자 ②: 사용자 주입)."""
    conn = get_connection()
    qid = conn.execute(
        "INSERT INTO questions (text, narrative_id, source_doc_id, created_by, status) VALUES (?, ?, ?, ?, 'tracking')",
        (text.strip(), narrative_id, source_doc_id, created_by)).lastrowid
    conn.commit()
    conn.close()
    r = _decompose_and_track(qid, text)
    if "error" in r:
        _hard_delete(qid)   # 빈 질문 잔재 방지
    return r


def _decompose_and_track(qid: int, text: str) -> dict:
    """질문 qid를 분해(sonnet)→적재→numeric/sentiment 추출→판정. 신규·승인 공용."""
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return {"error": "llm 미가용"}
    try:
        raw = _call_claude_code(_DECOMPOSE_PROMPT.format(question=text), model="sonnet", timeout=240)
        plan = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception as e:  # noqa: BLE001
        return {"error": f"분해 실패: {e}"}

    conn = get_connection()
    has_numeric = has_corpus = False
    for sq in plan.get("sub_questions", []):
        sqid = conn.execute(
            "INSERT INTO sub_questions (question_id, text, falsifier) VALUES (?, ?, ?)",
            (qid, (sq.get("text") or "").strip(), (sq.get("falsifier") or "").strip() or None)).lastrowid
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
            elif modality == "sentiment":
                has_corpus = True
    conn.execute("UPDATE questions SET status='tracking' WHERE id=?", (qid,))
    conn.commit()
    conn.close()

    # 관측 추출은 event-driven — 여기선 최초 분해 시 1회. numeric=컨콜, sentiment=코퍼스(게으른 haiku).
    if has_numeric:
        try:
            from pipeline.transcript import extract_proxies
            extract_proxies(limit=40)
        except Exception as e:  # noqa: BLE001
            print(f"[question] numeric 추출 실패: {e}")
    if has_corpus:
        try:
            extract_sentiment_proxies(question_id=qid)
        except Exception as e:  # noqa: BLE001
            print(f"[question] sentiment 추출 실패: {e}")

    rollup(qid)
    return get_tree(qid)


def _hard_delete(qid: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM proxy_observations WHERE proxy_id IN "
                 "(SELECT id FROM proxy_registry WHERE sub_question_id IN "
                 "(SELECT id FROM sub_questions WHERE question_id=?))", (qid,))
    conn.execute("DELETE FROM proxy_registry WHERE sub_question_id IN "
                 "(SELECT id FROM sub_questions WHERE question_id=?)", (qid,))
    conn.execute("DELETE FROM sub_questions WHERE question_id=?", (qid,))
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    conn.commit()
    conn.close()


# ---------- Q5 단일 소스 딥다이브 (소스→질문 도출 + 파급 시나리오) ----------

_DERIVE_PROMPT = """당신은 투자 리서치 애널리스트다. 아래 '단일 소스'(뉴스/글/영상)를 읽고, 투자자가
딥다이브할 가치가 있는 **핵심질문 1~3개**를 뽑아라. 많이 회자되지 않았어도 미래를 상상하게 만드는 각도를
우선하라(예: "이 재료가 특정 기업의 EPS·멀티플 리레이팅을 부를 수 있는가?"). 그리고 이 소스가 함의하는
**파급 사건(event) 한 문장**(시나리오 분석용)을 하나 도출하라.

[소스 제목] {title}
[소스 본문]
{body}

JSON만: {{"candidates": ["핵심질문1", "핵심질문2"], "event": "파급 분석용 사건 한 문장"}}"""


def derive_questions_from_doc(doc_id: int) -> dict:
    """단일 소스 문서에서 딥다이브 핵심질문 후보 + 파급 event 도출 (Q5, sonnet). 생성 안 함 — 후보 반환만."""
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return {"error": "llm 미가용"}
    conn = get_connection()
    doc = conn.execute(
        "SELECT rd.title, rd.markdown, e.summary FROM raw_documents rd "
        "LEFT JOIN enrichments e ON e.doc_id=rd.id WHERE rd.id=?", (doc_id,)).fetchone()
    conn.close()
    if not doc:
        return {"error": "문서 없음"}
    body = (doc["markdown"] or doc["summary"] or "")[:12000]
    if not body.strip():
        return {"error": "본문 없음"}
    try:
        raw = _call_claude_code(_DERIVE_PROMPT.format(title=doc["title"] or "", body=body), model="sonnet", timeout=180)
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception as e:  # noqa: BLE001
        return {"error": f"도출 실패: {e}"}
    cands = [c.strip() for c in (d.get("candidates") or []) if isinstance(c, str) and c.strip()][:3]
    return {"doc_id": doc_id, "title": doc["title"], "candidates": cands, "event": (d.get("event") or "").strip()}


def run_scenario_for_event(event: str, question_id: int | None = None) -> dict:
    """단일 소스 event로 파급 시나리오 생성 + scenarios 캐시. 질문=허브(D-070): question_id로 질문에 묶는다.
    topic은 짧은 라벨(질문 텍스트 앞부분)로 — 긴 event 문장이 피드에서 내러티브로 오인되던 것 교정."""
    from pipeline.scenario import build_scenario
    if not event.strip():
        return {"error": "event 비어 있음"}
    r = build_scenario(event)
    if r.get("error"):
        return {"error": r["error"]}
    # 피드 표시용 짧은 topic 라벨 (질문에 묶였으면 질문 텍스트, 아니면 event 앞부분)
    label = event.strip()
    conn = get_connection()
    if question_id:
        q = conn.execute("SELECT text FROM questions WHERE id=?", (question_id,)).fetchone()
        if q:
            label = q["text"][:60]
    conn.execute(
        "INSERT INTO scenarios (topic, event, answer, beneficiaries, citations, narrative_version, question_id, model, created_at) "
        "VALUES (?,?,?,?,?,NULL,?,?,datetime('now')) ON CONFLICT(topic) DO UPDATE SET "
        "event=excluded.event, answer=excluded.answer, beneficiaries=excluded.beneficiaries, "
        "citations=excluded.citations, question_id=excluded.question_id, model=excluded.model, created_at=excluded.created_at",
        (label, event, r.get("answer"), json.dumps(r.get("beneficiaries") or [], ensure_ascii=False),
         json.dumps(r.get("citations") or [], ensure_ascii=False), question_id, r.get("model")))
    conn.commit()
    conn.close()
    return {"topic": label, "answer": r.get("answer"), "beneficiaries": r.get("beneficiaries") or []}


# ---------- 생성자 ① 자동 도출 (지배 내러티브 → 제안 큐, D-067) ----------

def propose_from_narratives(limit: int = 3) -> dict:
    """지배 내러티브(인과엣지 多·최신)의 질문형 제목을 질문 후보로 제안(status='proposed').
    분해는 하지 않는다 — 비싼 노동은 승인 뒤로(D-020). 승인 시 approve_question이 분해."""
    conn = get_connection()
    # topic별 최신(non-superseded) 내러티브 중 인과엣지 수(=영향력)로 랭킹
    rows = conn.execute(
        "SELECT n.id, n.topic, n.title, "
        "  (SELECT COUNT(*) FROM entity_relations er WHERE er.narrative_id=n.id) AS power "
        "FROM narratives n "
        "WHERE n.superseded_at IS NULL AND n.title IS NOT NULL AND n.kind='topic' "
        "ORDER BY power DESC, n.created_at DESC LIMIT 40").fetchall()
    proposed = 0
    for r in rows:
        if proposed >= limit:
            break
        # 이미 이 내러티브에서 만든 질문(제안·추적 불문)이 있으면 스킵
        exists = conn.execute(
            "SELECT 1 FROM questions WHERE narrative_id=? AND status != 'dismissed'", (r["id"],)).fetchone()
        if exists or not (r["title"] or "").strip():
            continue
        conn.execute(
            "INSERT INTO questions (text, narrative_id, created_by, status) VALUES (?, ?, 'system', 'proposed')",
            (r["title"].strip(), r["id"]))
        proposed += 1
    conn.commit()
    conn.close()
    return {"proposed": proposed}


def approve_question(question_id: int) -> dict:
    """제안된 질문을 승인 → 분해·추적 시작 (비싼 sonnet 분해는 여기서, 승인 뒤)."""
    conn = get_connection()
    q = conn.execute("SELECT text, status FROM questions WHERE id=?", (question_id,)).fetchone()
    conn.close()
    if not q:
        return {"error": "질문 없음"}
    if q["status"] != "proposed":
        return get_tree(question_id)
    return _decompose_and_track(question_id, q["text"])


_INSIGHT_Q_PROMPT = """다음은 '{name}' 종목의 최근 다이제스트에서 포착된 '새로운 시각'(관찰)이다.
투자자가 앞으로 추적할 가치가 있는 **핵심질문 1개**로 바꿔라 — 반드시 의문형, 판정 가능하게(예/아니오로 수렴).
관찰이 추적할 질문거리가 아니면(단순 사실 확인·이미 종결) question을 null로.

관찰: {insight}

JSON만: {{"question": "의문형 핵심질문 또는 null"}}"""


def _insight_to_question(name: str, insight: str) -> str | None:
    """다이제스트 insight(서술문) → 추적 가능한 의문형 핵심질문 (haiku). 질문거리 아니면 None."""
    from pipeline.enrich import _call_claude_code
    try:
        raw = _call_claude_code(_INSIGHT_Q_PROMPT.format(name=name, insight=insight[:600]),
                                model="haiku", timeout=60)
        q = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("question")
        return q.strip() if isinstance(q, str) and q.strip() and q.strip().lower() != "null" else None
    except Exception:  # noqa: BLE001
        return None


def propose_from_digests(budget: int = 5) -> dict:
    """팔로우(워치리스트) 기업의 1W/1M 다이제스트 '새로운 시각'을 질문형으로 변환해 제안 큐에 적재
    (다이제스트 언섬, D-085 — 매일 버려지던 발견을 능동 추적으로). 승인 시에만 추적(D-020).
    insight_proposed 플래그로 dedup(시도 1회), budget 상한으로 비용 천장 고정([[D-072]])."""
    from pipeline.enrich import llm_available
    if not llm_available():
        return {"proposed": 0}
    conn = get_connection()
    rows = conn.execute("""
        SELECT ed.id, e.name, ed.period, ed.insights FROM entity_digests ed
        JOIN entities e ON e.id = ed.entity_id
        JOIN watchlist w ON w.stock_code = e.aliases
        WHERE ed.period IN ('1w','1m') AND ed.insights IS NOT NULL
          AND COALESCE(ed.insight_proposed, 0) = 0
        ORDER BY (ed.period='1m') DESC, ed.period_start DESC LIMIT ?""", (budget,)).fetchall()
    proposed = 0
    for r in rows:
        q = _insight_to_question(r["name"], r["insights"])
        if q and not conn.execute(
                "SELECT 1 FROM questions WHERE text=? AND status != 'dismissed'", (q,)).fetchone():
            conn.execute("INSERT INTO questions (text, created_by, status) VALUES (?, 'digest', 'proposed')", (q,))
            proposed += 1
        conn.execute("UPDATE entity_digests SET insight_proposed=1 WHERE id=?", (r["id"],))  # 시도 dedup(성패 무관)
    conn.commit()
    conn.close()
    return {"proposed": proposed}


def refresh_all(propose: int = 3) -> dict:
    """일 1회 cron — 자동도출 + 관측 갱신(numeric 컨콜·sentiment 코퍼스) + 전 추적 질문 재판정.
    event-driven 편승: 새 컨콜/문서 없으면 멱등 스킵으로 사실상 no-op(D-068)."""
    out: dict = {"proposed": 0, "digest_proposed": 0, "numeric": 0, "sentiment": 0, "rerolled": 0}
    out["proposed"] = propose_from_narratives(limit=propose).get("proposed", 0)
    try:
        out["digest_proposed"] = propose_from_digests().get("proposed", 0)   # 다이제스트 언섬(D-085)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] digest 제안 실패: {e}")
    try:
        from pipeline.transcript import extract_proxies
        out["numeric"] = extract_proxies(limit=40).get("extracted", 0)   # 새 컨콜만 (멱등)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] numeric 실패: {e}")
    try:
        out["sentiment"] = extract_sentiment_proxies().get("extracted", 0)  # 전 sentiment 프록시, 하루 1회 멱등
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] sentiment 실패: {e}")
    conn = get_connection()
    ids = [r["id"] for r in conn.execute("SELECT id FROM questions WHERE status='tracking'").fetchall()]
    conn.close()
    for qid in ids:
        rollup(qid)
    out["rerolled"] = len(ids)
    return out


_SENTIMENT_PROMPT = """다음은 '{label}'에 대한 최근 투자자 문서 발췌다. 이 주제의 시장 여론/심리가
최근 어느 방향으로 움직이는지 판정하라. 추정 금지 — 발췌에 근거만. 근거가 약하면 flat.
[무엇을 볼지] {hint}

JSON만: {{"direction":"up|down|flat", "value_text":"판정 근거 한 문장(한국어)"}}

[최근 문서 발췌]
{snippets}"""


def extract_sentiment_proxies(question_id: int | None = None, budget: int = 20,
                              active_days: int = 14, per_proxy_docs: int = 8) -> dict:
    """sentiment 프록시를 코퍼스에서 게으른 haiku로 판정 (D-068 선행층).
    하루 1회(source_id=KST 날짜 버킷) 멱등. **비용 가드(D-072)**: cron 경로(question_id=None)는
    (1) 활성 질문만(최근 active_days 내 조회/생성 — dormant 일시정지) (2) 회당 budget 상한, 가장 오래
    안 본 프록시 우선(라운드로빈) → 일일 비용이 질문 수와 무관하게 천장 고정. 특정 질문 지정 시엔 전부(초기 분해)."""
    from datetime import datetime, timedelta, timezone
    from pipeline.enrich import _call_claude_code, llm_available
    from pipeline.search import search
    if not llm_available():
        return {"extracted": 0, "reason": "llm 미가용"}
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    conn = get_connection()
    where = ["pr.active=1", "pr.modality='sentiment'"]
    params: list = []
    if question_id is not None:
        where.append("sq.question_id = ?")
        params.append(question_id)
        limit = 1000                       # 특정 질문 초기 분해 — 전부
    else:
        where.append("q.status='tracking'")
        where.append(f"COALESCE(q.last_viewed_at, q.created_at) >= datetime('now', '-{int(active_days)} days')")
        limit = budget                     # cron — 활성 질문 + 예산 상한
    # 오늘 이미 관측한 프록시 제외 + 라운드로빈(가장 오래 안 본 것 우선, 미관측 최우선)
    proxies = conn.execute(
        f"SELECT pr.id, pr.label, pr.extract_hint, pr.yes_direction, "
        f"  (SELECT MAX(observed_at) FROM proxy_observations po WHERE po.proxy_id=pr.id AND po.source_type='corpus') AS last_obs "
        f"FROM proxy_registry pr "
        f"JOIN sub_questions sq ON sq.id = pr.sub_question_id "
        f"JOIN questions q ON q.id = sq.question_id "
        f"WHERE {' AND '.join(where)} "
        f"  AND NOT EXISTS (SELECT 1 FROM proxy_observations po2 WHERE po2.proxy_id=pr.id "
        f"                  AND po2.source_type='corpus' AND po2.source_id=?) "
        f"ORDER BY last_obs ASC LIMIT ?",   # SQLite: NULL(미관측)이 asc 최상단
        (*params, today, limit)).fetchall()
    extracted = 0
    for p in proxies:
        dup = conn.execute(
            "SELECT 1 FROM proxy_observations WHERE proxy_id=? AND source_type='corpus' AND source_id=?",
            (p["id"], today)).fetchone()
        if dup:
            continue
        hits = search(f"{p['label']} {p['extract_hint'] or ''}".strip(), k=per_proxy_docs)
        if not hits:
            continue
        ids = [h["doc_id"] for h in hits]
        docs = conn.execute(
            f"SELECT rd.title, e.summary FROM raw_documents rd LEFT JOIN enrichments e ON e.doc_id=rd.id "
            f"WHERE rd.id IN ({','.join('?' * len(ids))})", ids).fetchall()
        snippets = "\n".join(f"- {(d['title'] or '')[:80]}: {(d['summary'] or '')[:200]}" for d in docs)
        if not snippets.strip():
            continue
        try:
            raw = _call_claude_code(
                _SENTIMENT_PROMPT.format(label=p["label"], hint=p["extract_hint"] or "", snippets=snippets[:8000]),
                model="haiku", timeout=120)
            d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            print(f"[sentiment] {p['label']} 실패: {e}")
            continue
        direction = d.get("direction") if d.get("direction") in ("up", "down", "flat") else None
        conn.execute(
            "INSERT INTO proxy_observations (proxy_id, source_type, source_id, observed_at, value_text, direction) "
            "VALUES (?, 'corpus', ?, ?, ?, ?)",
            (p["id"], today, today, d.get("value_text"), direction))
        conn.commit()
        extracted += 1
    conn.close()
    return {"extracted": extracted}


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
    # 허브(D-070): 이 질문에 묶인 파급 시나리오 + 소스 문서
    sc = conn.execute(
        "SELECT event, answer, beneficiaries, created_at FROM scenarios WHERE question_id=? ORDER BY created_at DESC LIMIT 1",
        (question_id,)).fetchone()
    tree["scenario"] = ({"event": sc["event"], "answer": sc["answer"],
                         "beneficiaries": json.loads(sc["beneficiaries"] or "[]"),
                         "created_at": sc["created_at"]} if sc else None)
    if tree.get("source_doc_id"):
        src = conn.execute("SELECT id, title, source_type FROM raw_documents WHERE id=?", (tree["source_doc_id"],)).fetchone()
        tree["source_doc"] = dict(src) if src else None
    conn.close()
    return tree


def list_questions(narrative_id: int | None = None, status: str | None = None) -> list[dict]:
    conn = get_connection()
    where = ["status != 'dismissed'"]
    params: list = []
    if narrative_id is not None:
        where.append("narrative_id = ?")
        params.append(narrative_id)
    if status:
        where.append("status = ?")
        params.append(status)
    rows = conn.execute(
        "SELECT q.*, (SELECT COUNT(*) FROM sub_questions sq WHERE sq.question_id=q.id) AS sub_count "
        f"FROM questions q WHERE {' AND '.join(where)} ORDER BY updated_at DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_proxy_detail(proxy_id: int) -> dict | None:
    """프록시 1개 디테일 — 메타(무엇을 측정·'예' 방향·하위질문) + 전체 관측 시계열(출처 포함, LLM 0)."""
    conn = get_connection()
    p = conn.execute(
        "SELECT pr.id, pr.label, pr.modality, pr.yes_direction, pr.unit, pr.tickers, pr.extract_hint, "
        "  sq.text AS sub_question_text, q.id AS question_id, q.text AS question_text "
        "FROM proxy_registry pr "
        "LEFT JOIN sub_questions sq ON sq.id = pr.sub_question_id "
        "LEFT JOIN questions q ON q.id = sq.question_id "
        "WHERE pr.id=?", (proxy_id,)).fetchone()
    if not p:
        conn.close()
        return None
    rows = conn.execute(
        "SELECT o.observed_at, o.value_num, o.value_text, o.direction, o.confidence, o.source_type, "
        "  t.raw_doc_id, t.ticker, t.fiscal_year, t.fiscal_period "
        "FROM proxy_observations o LEFT JOIN transcripts t ON t.id = o.transcript_id "
        "WHERE o.proxy_id=? ORDER BY o.observed_at DESC, o.id DESC LIMIT 60", (proxy_id,)).fetchall()
    conn.close()
    obs = []
    for o in rows:
        src = None
        if o["raw_doc_id"]:
            lbl = o["ticker"] or ""
            if o["fiscal_year"] and o["fiscal_period"]:
                lbl = f"{lbl} {o['fiscal_year']}{o['fiscal_period']}".strip()
            src = {"doc_id": o["raw_doc_id"], "label": lbl or "컨콜"}
        elif o["source_type"] == "corpus":
            src = {"doc_id": None, "label": "코퍼스 여론"}
        obs.append({"observed_at": o["observed_at"], "value_num": o["value_num"],
                    "value_text": o["value_text"], "direction": o["direction"],
                    "confidence": o["confidence"], "source": src})
    return {"id": p["id"], "label": p["label"], "modality": p["modality"],
            "yes_direction": p["yes_direction"], "unit": p["unit"], "tickers": p["tickers"],
            "extract_hint": p["extract_hint"], "sub_question_text": p["sub_question_text"],
            "question_id": p["question_id"], "question_text": p["question_text"], "observations": obs}


def dismiss_question(question_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE questions SET status='dismissed' WHERE id=?", (question_id,))
    conn.commit()
    conn.close()

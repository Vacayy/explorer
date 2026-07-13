"""종목 AI 브리프 — P2-1 (docs/specs/product-v3.md §3).

도시에 첫 화면: "지금 이 종목에서 알아야 할 것" — 언급 다이제스트·신호·일정·내 논지를
하나의 브리프로 종합하고, 내 논지와 새 증거의 충돌/지지를 별도 감지.

- 생성 시점: 열람 시 게으르게. inputs_hash(모든 입력의 지문)가 바뀐 경우에만 LLM 호출
- 종목별 in-flight 락 (source_dossier와 동일 — LLM 중복 호출 방지)
- LLM 호출은 트랜잭션 밖
"""
import hashlib
import json
import threading

from database import get_connection
from pipeline.digests import STYLE_RULES, _call_json
from pipeline.enrich import llm_engine

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _brief_lock(stock_code: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(stock_code, threading.Lock())


def _resolve_entity(conn, stock_code: str):
    return conn.execute(
        "SELECT id, name FROM entities WHERE type='company' AND aliases=?", (stock_code,)).fetchone()


def gather_inputs(conn, stock_code: str, entity_id: int) -> dict:
    """브리프 입력 수집 — 전부 기존 데이터, LLM 0토큰."""
    digests = {r["period"]: r for r in conn.execute("""
        SELECT period, period_start, digest, insights, doc_ids_hash FROM entity_digests
        WHERE entity_id=? AND period IN ('1d','7d')
        GROUP BY period HAVING period_start = max(period_start)""", (entity_id,))}
    signals = conn.execute("""
        SELECT id, signal_type, date, interpretation, payload_json FROM signals
        WHERE entity_id=? ORDER BY date DESC LIMIT 3""", (entity_id,)).fetchall()
    upcoming = conn.execute("""
        SELECT id, event_type, event_date, title FROM catalysts
        WHERE stock_code=? AND event_date >= date('now') ORDER BY event_date LIMIT 5
    """, (stock_code,)).fetchall()
    actions = conn.execute("""
        SELECT rcp_no, action_type, rcept_dt, summary FROM corporate_actions
        WHERE stock_code=? AND rcept_dt >= strftime('%Y%m%d', date('now','-30 days'))
        ORDER BY rcept_dt DESC LIMIT 3""", (stock_code,)).fetchall()
    thesis = conn.execute(
        "SELECT thesis, conviction, target_price, updated_at FROM watchlist WHERE stock_code=?",
        (stock_code,)).fetchone()
    notes = conn.execute("""
        SELECT id, memo_type, title, content, updated_at FROM ir_notes
        WHERE corp_code=(SELECT corp_code FROM companies WHERE stock_code=?)
           OR corp_code=?
        ORDER BY updated_at DESC LIMIT 12""", (stock_code, stock_code)).fetchall()
    from pipeline.knowledge_recall import recall_for_entity
    from pipeline.flows import flow_summary
    knowledge = recall_for_entity(conn, entity_id)  # K1: 승격 지식을 재료로
    consensus = conn.execute("""
        SELECT fiscal_year, fwd_eps, fwd_per, target_price, fetched_date
        FROM consensus_estimates WHERE stock_code=?
        ORDER BY fetched_date DESC, fiscal_year LIMIT 2""", (stock_code,)).fetchall()
    sentiment = conn.execute("""
        SELECT SUM(en.sentiment='positive') pos, SUM(en.sentiment='negative') neg,
               SUM(en.sentiment='neutral') neu
        FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
        JOIN enrichments en ON en.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='stock'
          AND rd.published_at >= datetime('now', '-30 days')""", (entity_id,)).fetchone()
    return {"digests": digests, "signals": signals, "upcoming": upcoming,
            "actions": actions, "thesis": thesis, "notes": notes, "knowledge": knowledge,
            "decomp": _price_decomposition(conn, stock_code),
            "consensus": consensus, "flows": flow_summary(conn, stock_code),
            "sentiment": dict(sentiment) if sentiment and (sentiment["pos"] or sentiment["neg"]) else None}


def _price_decomposition(conn, stock_code: str) -> dict | None:
    """상승 분해 (근사) — 12개월 주가 변화를 이익 변화 × 멀티플 변화로 (추세 패턴 §7 Step5).

    이익은 최신 연간 사업보고서 당기순이익 YoY (thstrm vs frmtrm). 적자 구간이면
    분해가 무의미하므로 None. LLM 0, 재무 데이터 없으면 None (Partial 허용).
    hash에는 넣지 않는다 — 매일 바뀌는 주가로 브리프가 재생성되지 않게 (보조 재료).
    """
    px = conn.execute("""
        SELECT (SELECT close FROM stock_prices WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1) cur,
               (SELECT close FROM stock_prices WHERE stock_code=?
                AND trade_date <= date('now', '-365 days') ORDER BY trade_date DESC LIMIT 1) base
    """, (stock_code, stock_code)).fetchone()
    if not px or not px["cur"] or not px["base"]:
        return None
    ni = conn.execute("""
        SELECT fs.thstrm_amount t, fs.frmtrm_amount f, fs.bsns_year
        FROM financial_statements fs
        JOIN companies c ON c.corp_code = fs.corp_code
        WHERE c.stock_code=? AND fs.reprt_code='11011' AND fs.sj_div IN ('IS','CIS')
          AND fs.account_nm LIKE '당기순이익%'
        ORDER BY fs.bsns_year DESC LIMIT 1""", (stock_code,)).fetchone()
    if not ni:
        return None
    try:
        t, f = int(ni["t"]), int(ni["f"])
    except (TypeError, ValueError):
        return None
    if t <= 0 or f <= 0:
        return None  # 적자 구간 — 멀티플 분해 무의미
    price_chg = (px["cur"] - px["base"]) / px["base"] * 100
    earnings_chg = (t - f) / f * 100
    multiple_chg = ((1 + price_chg / 100) / (1 + earnings_chg / 100) - 1) * 100
    return {"price_chg_12m": round(price_chg, 1), "earnings_chg_yoy": round(earnings_chg, 1),
            "multiple_chg": round(multiple_chg, 1), "year": ni["bsns_year"]}


def inputs_hash(inp: dict) -> str:
    parts = []
    for period, d in sorted(inp["digests"].items()):
        parts.append(f"dig:{period}:{d['period_start']}:{d['doc_ids_hash']}")
    parts += [f"sig:{s['id']}" for s in inp["signals"]]
    parts += [f"cat:{c['id']}:{c['event_date']}" for c in inp["upcoming"]]
    parts += [f"act:{a['rcp_no']}" for a in inp["actions"]]
    t = inp["thesis"]
    if t:
        parts.append(f"thesis:{t['thesis']}:{t['conviction']}:{t['target_price']}")
    parts += [f"note:{n['id']}:{n['updated_at']}" for n in inp["notes"]]
    # 지식 승인·증거 병합 시 브리프 재생성 (독립 관측 수가 지문에 포함)
    parts += [f"kn:{k['id']}:{k['independent_n']}:{k['refute_n']}" for k in inp["knowledge"]]
    # 컨센서스 revision(추정치 변경)은 의미 있는 새 정보 — 재생성 유발.
    # 수급(flows)·상승분해는 매일 바뀌는 보조 재료라 지문에 넣지 않는다
    parts += [f"cs:{c['fiscal_year']}:{c['fwd_eps']}:{c['target_price']}" for c in inp.get("consensus", [])]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _has_material(inp: dict) -> bool:
    return bool(inp["digests"] or inp["signals"] or inp["actions"] or inp["upcoming"])


def get_cached(conn, entity_id: int):
    """최신 브리프 — append-only 히스토리에서 max(id)."""
    return conn.execute(
        "SELECT brief, thesis_check, revision_call, inputs_hash, created_at FROM stock_briefs "
        "WHERE entity_id=? ORDER BY id DESC LIMIT 1", (entity_id,)).fetchone()


def _build_prompt(name: str, inp: dict) -> str:
    blocks = []
    for period, d in sorted(inp["digests"].items()):
        label = "오늘 언급 요약" if period == "1d" else "최근 7일 요약"
        blocks.append(f"[{label} · {d['period_start']}]\n{d['digest'] or ''}"
                      + (f"\n(새로운 시각: {d['insights']})" if d["insights"] else ""))
    if inp["signals"]:
        lines = []
        for s in inp["signals"]:
            p = json.loads(s["payload_json"] or "{}")
            desc = f"언급 급증 7일 {p.get('count_7d')}회" if s["signal_type"] == "mention_surge" \
                else f"52주 신고가 +{p.get('breakout_pct')}%" if s["signal_type"] == "high_52w" \
                else s["signal_type"]
            lines.append(f"- {s['date']} {desc}" + (f" — {s['interpretation']}" if s["interpretation"] else ""))
        blocks.append("[신호]\n" + "\n".join(lines))
    if inp["actions"]:
        blocks.append("[최근 30일 기업활동 공시]\n" + "\n".join(
            f"- {a['rcept_dt']} {a['action_type']}: {(a['summary'] or '')[:150]}" for a in inp["actions"]))
    if inp["upcoming"]:
        blocks.append("[다가오는 일정]\n" + "\n".join(
            f"- {c['event_date']} {c['event_type']}: {c['title']}" for c in inp["upcoming"]))
    if inp.get("decomp"):
        d = inp["decomp"]
        blocks.append(
            f"[상승 분해 (근사 — {d['year']}년 연간 실적 기준)]\n"
            f"12개월 주가 {d['price_chg_12m']:+}% = 순이익 YoY {d['earnings_chg_yoy']:+}% × "
            f"멀티플 {d['multiple_chg']:+}% — 멀티플 기여가 크면 '기대'가, "
            f"이익 기여가 크면 '실적'이 주도한 상승이다")
    if inp.get("consensus"):
        lines = [f"- {c['fiscal_year'][:4]}E: Fwd EPS {c['fwd_eps']:,.0f}원 · Fwd PER {c['fwd_per']}배"
                 + (f" · 목표주가 평균 {c['target_price']:,.0f}원" if c["target_price"] else "")
                 for c in inp["consensus"] if c["fwd_eps"]]
        if lines:
            blocks.append("[현재 컨센서스 — 시장의 기대치]\n" + "\n".join(lines))
    if inp.get("flows"):
        f = inp["flows"]
        def _fmt(v):
            return f"{v/10000:+,.0f}만주" if v is not None else "-"
        blocks.append(
            f"[수급 — 최근 {f['days']}거래일 누적 순매수]\n"
            f"외국인 {_fmt(f['foreign_net'])} · 기관 {_fmt(f['inst_net'])} · 개인 {_fmt(f['indiv_net'])}"
            + (f" · 외인 보유율 {f['foreign_hold_ratio']}%" if f["foreign_hold_ratio"] else ""))
    if inp.get("sentiment"):
        s = inp["sentiment"]
        blocks.append(f"[감성 온도 — 최근 30일 언급 문서]\n"
                      f"긍정 {s['pos'] or 0} · 부정 {s['neg'] or 0} · 중립 {s['neu'] or 0}")
    if inp["knowledge"]:
        from pipeline.knowledge_recall import knowledge_block
        blocks.append(knowledge_block(
            inp["knowledge"],
            "승격된 지식 — 이 종목에 대해 시스템이 반복·독립 관측으로 검증한 전제. "
            "구조/체제층은 판단의 기반으로, 오늘의 재료를 이 위에서 해석해라").strip())

    thesis_block = ""
    t = inp["thesis"]
    notes = inp["notes"]
    if (t and t["thesis"]) or notes:
        lines = []
        if t and t["thesis"]:
            lines.append(f"핵심 논지: {t['thesis']} (확신도 {t['conviction']}/5"
                         + (f", 목표가 {t['target_price']:,}원" if t["target_price"] else "") + ")")
        for n in notes:
            lines.append(f"- [{n['memo_type']}] {n['title']}: {(n['content'] or '')[:100]}")
        thesis_block = "\n\n[사용자의 투자 논지 — thesis_check 판단 기준]\n" + "\n".join(lines)

    from pipeline.lenses import LENS_PATTERN
    return (
        f"너는 '{name}' 담당 애널리스트다. 아래 수집된 재료로 관점 있는 브리프를 써라 — "
        "재료 나열이 아니라 콜이다.\n"
        "브리프 마크다운 구조 (해당 재료가 없으면 그 섹션은 생략):\n"
        "(첫 문단) 핵심 종합 — 지금 이 종목에서 알아야 할 것 2~3문장\n"
        "### 가격의 전제 — 현재가는 어떤 기대(컨센서스 EPS·멀티플·목표가) 위에 서 있나. "
        "'현재 추정치가 ~라는 전제인데'를 명시\n"
        "### 전제 vs 관측 — 최근 관측(언급 요약·신호·수급·지식)이 그 전제를 지지하는가 이탈하는가. "
        "추정치가 더 오를/내릴 근거가 보이면 명시\n"
        "### 유의할 챌린지 — 지금 내러티브에 도전이 될 수 있는 것 (반박 증거·상충 관측·과열 신호). "
        "'이 부분 유의해서 봐야 한다'까지\n"
        "### 심리와 위치 — 시장 온도(환호/중립/절망, 감성·수급 근거)와 위치 판단. "
        "가능하면 '하방 탄탄·상방 열림' 같은 비대칭 구조로 결론 (근거 없으면 판단 유보 명시)\n"
        + LENS_PATTERN + "\n"
        + STYLE_RULES +
        'JSON만 출력: {"brief": "마크다운 브리프", "thesis_check": "사용자 논지와 새 증거가 '
        "충돌하거나 강하게 지지되는 지점이 있으면 1~3문장 (어느 쪽인지 명시), 논지가 없거나 "
        '특이사항 없으면 null", '
        '"revision_call": {"direction": "up|down|hold", "rationale": "1~2문장"} 또는 null}\n'
        "revision_call 규칙: 위 재료(승격 지식·언급 요약·신호·수급)를 근거로 향후 1~2개월 "
        "이익 컨센서스가 상향/하향/유지될 가능성을 판단해라. 반드시 재료의 구체 근거를 대라 — "
        "재료가 방향 판단에 불충분하면 null. 이 콜은 기록되어 실제 추정치 변화와 대조된다.\n"
        + thesis_block + "\n\n[재료]\n" + "\n\n".join(blocks)
    )


def compute_brief(stock_code: str) -> dict:
    """입력이 바뀌었으면 haiku로 브리프 생성, 아니면 캐시 반환."""
    with _brief_lock(stock_code):
        return _compute_locked(stock_code)


def _compute_locked(stock_code: str) -> dict:
    conn = get_connection()
    ent = _resolve_entity(conn, stock_code)
    if not ent:
        conn.close()
        return {"status": "not_found"}

    inp = gather_inputs(conn, stock_code, ent["id"])
    if not _has_material(inp):
        conn.close()
        return {"status": "empty", "brief": None, "thesis_check": None, "created_at": None}

    h = inputs_hash(inp)
    cached = get_cached(conn, ent["id"])
    if cached and cached["inputs_hash"] == h:
        conn.close()
        return {"status": "cached", "brief": cached["brief"],
                "thesis_check": cached["thesis_check"],
                "revision_call": _parse_call(cached["revision_call"]),
                "created_at": cached["created_at"]}

    if llm_engine() != "claude-code":
        conn.close()
        return {"status": "unavailable",
                "brief": cached["brief"] if cached else None,
                "thesis_check": cached["thesis_check"] if cached else None,
                "revision_call": _parse_call(cached["revision_call"]) if cached else None,
                "created_at": cached["created_at"] if cached else None}

    prompt = _build_prompt(ent["name"], inp)
    try:
        data = _call_json(prompt)  # LLM 호출 — 쓰기 트랜잭션 밖
    except Exception:
        conn.close()
        return {"status": "failed",
                "brief": cached["brief"] if cached else None,
                "thesis_check": cached["thesis_check"] if cached else None,
                "revision_call": _parse_call(cached["revision_call"]) if cached else None,
                "created_at": cached["created_at"] if cached else None}

    # append-only: 재생성마다 새 행 = 히스토리 축적 (지난 시점 브리프 열람 +
    # revision_call은 나중에 실제 컨센서스 변화와 대조해 적중 평가)
    call = data.get("revision_call")
    conn.execute("""
        INSERT INTO stock_briefs (entity_id, brief, thesis_check, revision_call, inputs_hash, model)
        VALUES (?, ?, ?, ?, ?, 'claude-code/haiku')
    """, (ent["id"], data.get("brief"), data.get("thesis_check") or None,
          json.dumps(call, ensure_ascii=False) if call else None, h))
    conn.commit()
    row = get_cached(conn, ent["id"])
    conn.close()
    return {"status": "fresh", "brief": row["brief"], "thesis_check": row["thesis_check"],
            "revision_call": _parse_call(row["revision_call"]), "created_at": row["created_at"]}


def _parse_call(raw) -> dict | None:
    if not raw:
        return None
    try:
        c = json.loads(raw)
        return c if isinstance(c, dict) and c.get("direction") in ("up", "down", "hold") else None
    except Exception:
        return None

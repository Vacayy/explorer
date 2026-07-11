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
    knowledge = recall_for_entity(conn, entity_id)  # K1: 승격 지식을 재료로
    return {"digests": digests, "signals": signals, "upcoming": upcoming,
            "actions": actions, "thesis": thesis, "notes": notes, "knowledge": knowledge}


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
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _has_material(inp: dict) -> bool:
    return bool(inp["digests"] or inp["signals"] or inp["actions"] or inp["upcoming"])


def get_cached(conn, entity_id: int):
    """최신 브리프 — append-only 히스토리에서 max(id)."""
    return conn.execute(
        "SELECT brief, thesis_check, inputs_hash, created_at FROM stock_briefs "
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

    return (
        f"너는 '{name}' 담당 애널리스트다. 아래 수집된 재료로 \"지금 이 종목에서 알아야 할 것\" 브리프를 써라.\n"
        "재료를 나열하지 말고 종합해라 — 무엇이 중요하고 무엇이 연결되는지.\n"
        + STYLE_RULES +
        'JSON만 출력: {"brief": "마크다운 브리프", "thesis_check": "사용자 논지와 새 증거가 '
        "충돌하거나 강하게 지지되는 지점이 있으면 1~3문장 (어느 쪽인지 명시), 논지가 없거나 "
        '특이사항 없으면 null"}\n'
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
                "thesis_check": cached["thesis_check"], "created_at": cached["created_at"]}

    if llm_engine() != "claude-code":
        conn.close()
        return {"status": "unavailable",
                "brief": cached["brief"] if cached else None,
                "thesis_check": cached["thesis_check"] if cached else None,
                "created_at": cached["created_at"] if cached else None}

    prompt = _build_prompt(ent["name"], inp)
    try:
        data = _call_json(prompt)  # LLM 호출 — 쓰기 트랜잭션 밖
    except Exception:
        conn.close()
        return {"status": "failed",
                "brief": cached["brief"] if cached else None,
                "thesis_check": cached["thesis_check"] if cached else None,
                "created_at": cached["created_at"] if cached else None}

    # append-only: 재생성마다 새 행 = 히스토리 축적 (지난 시점 브리프 열람용)
    conn.execute("""
        INSERT INTO stock_briefs (entity_id, brief, thesis_check, inputs_hash, model)
        VALUES (?, ?, ?, ?, 'claude-code/haiku')
    """, (ent["id"], data.get("brief"), data.get("thesis_check") or None, h))
    conn.commit()
    row = get_cached(conn, ent["id"])
    conn.close()
    return {"status": "fresh", "brief": row["brief"], "thesis_check": row["thesis_check"],
            "created_at": row["created_at"]}

"""에이전트 제안함 — 시스템이 스스로 '뭘 조사할지' 포착해 제안 (진화계획 3단계 v1, D-020·D-022 계승).

docs/specs/agent-proposals.md. 제안-전용: 감지는 전부 자동, 실행은 항상 사람 승인 후.
kind 4종: neglect(소외 종목) · contested_edge(상충 인과) · devils_advocate(반대 관점 질문)
· falsifier_watch(딛고 선 전제의 반증 조건 리마인드).
"""
import json
import os
import subprocess

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

DEVILS_MODEL = os.getenv("DEVILS_MODEL", "haiku")


def _insert(conn, kind: str, title: str, rationale: str, payload: dict, dedup_key: str) -> bool:
    """멱등 제안 삽입 — 같은 (kind, dedup_key)가 이미 있으면(상태 무관) 재제안 안 함."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO agent_proposals (kind, title, rationale, payload_json, dedup_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, title, rationale, json.dumps(payload, ensure_ascii=False), dedup_key))
    return cur.rowcount > 0


def scan_neglect(conn) -> int:
    """소외 종목 → 리서치 제안 (BACKLOG '소외 스캐너' 흡수). 감지는 기존 neglect 신호 재사용, LLM 0."""
    made = 0
    for r in conn.execute("""
        SELECT s.entity_id, e.name, e.aliases stock_code, s.payload_json
        FROM signals s JOIN entities e ON e.id = s.entity_id
        WHERE s.signal_type='neglect'
          AND s.date = (SELECT MAX(date) FROM signals WHERE signal_type='neglect')
    """).fetchall():
        p = json.loads(r["payload_json"] or "{}")
        made += _insert(
            conn, "neglect",
            f"{r['name']} — 괜찮은데 아무도 말하지 않는 종목, 리서치해볼까요?",
            f"PER {p.get('per')}배 · ROE {p.get('roe')}% · 30일 언급 0건 — 주목의 부재가 비효율(기회)일 수 있음",
            {"entity_id": r["entity_id"], "stock_code": r["stock_code"], **p},
            f"stock:{r['stock_code']}")
    return made


def scan_contested_edges(conn) -> int:
    """역방향 CAUSES 쌍(A→B와 B→A 공존) → 조정 제안. LLM 0 감지.
    주의: 시점이 다른 나선(합법 피드백, D-027)일 수 있으므로 reference_period가 서로 다르면 제외."""
    made = 0
    for r in conn.execute("""
        SELECT e1.id id_a, e2.id id_b, s.name a, d.name b,
               e1.mechanism m_a, e2.mechanism m_b,
               e1.reference_period rp_a, e2.reference_period rp_b
        FROM entity_relations e1
        JOIN entity_relations e2 ON e2.src_id=e1.dst_id AND e2.dst_id=e1.src_id
          AND e2.rel_type='CAUSES' AND e1.id < e2.id
        JOIN entities s ON s.id=e1.src_id JOIN entities d ON d.id=e1.dst_id
        WHERE e1.rel_type='CAUSES'
    """).fetchall():
        if r["rp_a"] and r["rp_b"] and r["rp_a"] != r["rp_b"]:
            continue  # 시점이 갈린 나선 — 상충이 아니라 피드백(정상)
        made += _insert(
            conn, "contested_edge",
            f"'{r['a']}'와 '{r['b']}' 사이 인과 방향이 상충 — 검토해볼까요?",
            f"정방향: {r['m_a'] or '(메커니즘 없음)'} / 역방향: {r['m_b'] or '(메커니즘 없음)'} — 같은 시점에 양방향 주장",
            {"edge_a": r["id_a"], "edge_b": r["id_b"], "node_a": r["a"], "node_b": r["b"]},
            f"pair:{min(r['id_a'], r['id_b'])}-{max(r['id_a'], r['id_b'])}")
    return made


def scan_falsifier_watch(conn) -> int:
    """corroborated 지식의 미발화 반증 조건 → 가시성 리마인드 (액션 없음 — 감시는 기존
    watch_falsifiers가 함, 이건 '이 전제가 흔들리면 뭐가 달라지는지' 주기적 상기)."""
    made = 0
    for r in conn.execute("""
        SELECT kf.id fid, kf.condition, k.id kid, k.statement
        FROM knowledge_falsifiers kf JOIN knowledge k ON k.id = kf.knowledge_id
        WHERE kf.triggered_at IS NULL AND k.epistemic_status='corroborated'
          AND k.review_status='active' AND k.valid_to IS NULL
    """).fetchall():
        made += _insert(
            conn, "falsifier_watch",
            f"딛고 선 전제의 반증 조건 — {r['condition'][:60]}",
            f"전제: {r['statement'][:100]} — 이 조건이 발화하면 이 전제 위의 내러티브·판단이 흔들립니다",
            {"falsifier_id": r["fid"], "knowledge_id": r["kid"]},
            f"falsifier:{r['fid']}")
    return made


def scan_devils_advocate(conn) -> int:
    """내 논지에 대한 반대 관점 질문 (BACKLOG '불편한 질문 브리핑' 흡수, thesis_check의 능동형).
    watchlist 중 thesis가 있는 종목 대상, haiku. 주 1회 배치에서만 호출(비용)."""
    if llm_engine() != "claude-code":
        return 0
    rows = conn.execute(
        "SELECT stock_code, corp_name, thesis FROM watchlist "
        "WHERE thesis IS NOT NULL AND length(thesis) > 10").fetchall()
    made = 0
    for r in rows:
        # 종목당 미해소 devils_advocate가 이미 있으면 skip (질문 홍수 방지)
        if conn.execute(
            "SELECT 1 FROM agent_proposals WHERE kind='devils_advocate' AND status='proposed' "
            "AND dedup_key LIKE ?", (f"devil:{r['stock_code']}:%",)).fetchone():
            continue
        prompt = (
            "너는 투자 논지의 devil's advocate다. 아래 논지가 틀렸을 가장 그럴듯한 이유를 "
            "찌르는 질문 1개만 만들어라 — 막연한 반박 말고, 관측 가능한 사실로 검증할 수 있는 질문.\n"
            f"종목: {r['corp_name']}\n논지: {r['thesis']}\n"
            'JSON만 출력: {"question": "..."}')
        try:
            proc = subprocess.run(
                [_claude_bin(), "-p", "--model", DEVILS_MODEL, "--output-format", "json", prompt],
                capture_output=True, text=True, timeout=120)
            raw = json.loads(proc.stdout).get("result", "")
            q = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("question", "").strip()
        except Exception:
            continue
        if not q:
            continue
        made += _insert(
            conn, "devils_advocate",
            f"[{r['corp_name']}] {q[:100]}",
            f"내 논지: {r['thesis'][:100]} — 확증편향 방지용 불편한 질문",
            {"stock_code": r["stock_code"], "question": q},
            f"devil:{r['stock_code']}:{hash(q) % 100000}")
    return made


def run_all(include_llm: bool = True) -> dict:
    """전체 스캔 배치 — LLM 0 kind 3종은 항상, devils_advocate(haiku)는 include_llm일 때만."""
    conn = get_connection()
    stats = {
        "neglect": scan_neglect(conn),
        "contested_edge": scan_contested_edges(conn),
        "falsifier_watch": scan_falsifier_watch(conn),
    }
    if include_llm:
        stats["devils_advocate"] = scan_devils_advocate(conn)
    conn.commit()
    conn.close()
    return stats


def approve_proposal(proposal_id: int) -> dict:
    """승인 — kind별 액션 실행. neglect=stock_brief(opus), contested_edge=opus 조정,
    devils_advocate·falsifier_watch=확인만(액션 없음)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM agent_proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        conn.close()
        return {"status": "not_found"}
    if row["status"] != "proposed":
        conn.close()
        return {"status": row["status"]}
    payload = json.loads(row["payload_json"] or "{}")
    kind = row["kind"]
    conn.close()

    result: dict = {}
    if kind == "neglect" and payload.get("stock_code"):
        from pipeline.stock_brief import compute_brief
        r = compute_brief(payload["stock_code"])
        result = {"brief_status": r.get("status"), "revision_call": r.get("revision_call")}
    elif kind == "contested_edge":
        result = _resolve_contested(payload)
    # devils_advocate·falsifier_watch: 확인만 — 읽었다는 사실이 액션

    conn = get_connection()
    conn.execute(
        "UPDATE agent_proposals SET status='actioned', actioned_at=datetime('now'), result_json=? "
        "WHERE id=?", (json.dumps(result, ensure_ascii=False) if result else None, proposal_id))
    conn.commit()
    conn.close()
    return {"status": "actioned", "kind": kind, "result": result}


def _resolve_contested(payload: dict) -> dict:
    """상충 엣지 조정 — opus가 양방향 주장을 검토, 열세 방향 confidence 감점(0.7배).
    지식 승격·심사와 같은 다층 판단이라 opus 티어(KNOWLEDGE_MODEL 재사용)."""
    if llm_engine() != "claude-code":
        return {"verdict": "unavailable"}
    from pipeline.consolidation import _call_json
    conn = get_connection()
    edges = {}
    for key in ("edge_a", "edge_b"):
        r = conn.execute("""
            SELECT er.id, s.name f, d.name t, er.mechanism, er.confidence
            FROM entity_relations er JOIN entities s ON s.id=er.src_id
            JOIN entities d ON d.id=er.dst_id WHERE er.id=?""", (payload.get(key),)).fetchone()
        if r:
            edges[key] = dict(r)
    conn.close()
    if len(edges) < 2:
        return {"verdict": "edges_missing"}
    a, b = edges["edge_a"], edges["edge_b"]
    data = _call_json(
        "두 인과 주장이 서로 반대 방향이다. 어느 쪽이 더 타당한지 판정해라.\n"
        f"A: {a['f']} → {a['t']} ({a['mechanism'] or '메커니즘 없음'})\n"
        f"B: {b['f']} → {b['t']} ({b['mechanism'] or '메커니즘 없음'})\n"
        "가능한 판정: a_wins(A가 타당) | b_wins(B가 타당) | both_temporal(둘 다 맞음 — "
        "시점이 다른 피드백 루프) | unclear(판단 불가)\n"
        'JSON만 출력: {"verdict": "...", "rationale": "한 문장"}')
    verdict = data.get("verdict")
    conn = get_connection()
    if verdict == "a_wins":
        conn.execute("UPDATE entity_relations SET confidence=confidence*0.7 WHERE id=?", (b["id"],))
    elif verdict == "b_wins":
        conn.execute("UPDATE entity_relations SET confidence=confidence*0.7 WHERE id=?", (a["id"],))
    elif verdict == "both_temporal":
        # 상충이 아니라 시점 다른 피드백 나선(D-027) — 판정을 두 엣지에 물질화(D-029).
        # confidence는 유지하되 feedback_note에 근거를 남겨 ① contested 계산이 이 쌍을 제외하고
        # ② opus 근거가 result_json에만 갇혀 버려지지 않게 한다.
        note = data.get("rationale") or "opus 판정: 시점 다른 피드백 나선(both_temporal)"
        conn.execute("UPDATE entity_relations SET feedback_note=? WHERE id IN (?, ?)",
                     (note, a["id"], b["id"]))
    # unclear: 보류.
    conn.commit()
    conn.close()
    return {"verdict": verdict, "rationale": data.get("rationale")}


def dismiss_proposal(proposal_id: int) -> dict:
    conn = get_connection()
    conn.execute("UPDATE agent_proposals SET status='dismissed' WHERE id=? AND status='proposed'",
                 (proposal_id,))
    conn.commit()
    conn.close()
    return {"status": "dismissed"}

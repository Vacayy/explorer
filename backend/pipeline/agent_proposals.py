"""에이전트 제안함 — 시스템이 스스로 '뭘 조사할지' 포착해 제안 (진화계획 3단계 v1, D-020·D-022 계승).

docs/specs/agent-proposals.md. 제안-전용: 감지는 전부 자동, 실행은 항상 사람 승인 후.
kind 5종: neglect · contested_edge · devils_advocate · falsifier_watch · vocab_merge(유사 노드 통합, D-050)
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


VOCAB_MERGE_CAP = 30   # 타입별 판정 후보 상한 (sonnet 비용 통제) — D-062: 전역→타입별로 변경


def scan_vocab_merges(conn, cap: int = VOCAB_MERGE_CAP) -> int:
    """비슷하지만 별개인 노드 병합 제안 (D-050) — fastembed 후보 → sonnet same 판정 →
    승인 큐. 파괴적 병합(FK 재배선)이라 자동적용 대신 사람이 승인(D-020). 상위 유사도만(비용 통제).

    cap은 **타입별** 상한(D-062): theme의 고코사인 '어간 vs 어간+방향' 벽이 예산을 독식해
    sector·macro의 진짜 동의어가 판정조차 안 되는 걸 막는다. 각 타입 상위 cap쌍씩 판정.

    실패(fastembed·판정 엔진 미가용)는 삼키지 않고 raise — 호출부(run_all)가 job_runs에 error로
    남긴다. 예전엔 except→0으로 삼켜 '제안 0건 ok'로 둔갑, 실패가 관리자 페이지에서 안 보였다(D-055)."""
    from collections import defaultdict

    from pipeline.vocab import find_merge_candidates, judge_pairs, pick_survivor
    found = find_merge_candidates(conn)
    if found["reason"]:              # 후보 생성 degrade(fastembed 미설치 등) — 0 아니라 실패로 노출
        raise RuntimeError(found["reason"])
    by_type: dict[str, list] = defaultdict(list)   # 후보는 코사인 내림차순 → 타입별 상위 cap쌍
    for c in found["candidates"]:
        if len(by_type[c["type"]]) < cap:
            by_type[c["type"]].append(c)
    cands = [c for lst in by_type.values() for c in lst]
    if not cands:
        return 0
    judged = judge_pairs(cands)      # 엔진 미가용 시 RuntimeError — 그대로 전파
    made = 0
    for j in judged:
        if j.get("verdict") != "same":
            continue
        try:
            sid, lid = pick_survivor(conn, j["a_id"], j["b_id"])
        except Exception:
            continue
        names = {j["a_id"]: j["a_name"], j["b_id"]: j["b_name"]}
        made += _insert(
            conn, "vocab_merge",
            f"'{names.get(lid)}' → '{names.get(sid)}' 통합?",
            f"유사 노드 병합 제안 (유사도 {j.get('cosine')}). {j.get('rationale', '')}".strip(),
            {"survivor_id": sid, "survivor_name": names.get(sid), "loser_id": lid,
             "loser_name": names.get(lid), "type": j.get("type"), "cosine": j.get("cosine"),
             "rationale": j.get("rationale", "")},
            f"vocab:{sid}:{lid}")
    return made


def scan_report_suggestions(conn, cap: int = 5) -> int:
    """리포트 생성 제안 (D-051) — 파급 시나리오가 있는데 아직 (최신) 리포트가 없는 주제.
    리포트 생성은 비싸므로(opus 연쇄) 자동 생성 대신 '재료가 쌓였는데 만들까요?' 제안 → 승인 후 생성."""
    made = 0
    for r in conn.execute("""
        SELECT s.topic, n.v narrative_version
        FROM scenarios s
        JOIN (SELECT topic, MAX(version) v FROM narratives
              WHERE COALESCE(kind,'topic')='topic' GROUP BY topic) n ON n.topic = s.topic
        WHERE NOT EXISTS (SELECT 1 FROM reports r WHERE r.anchor_topic = s.topic)
        ORDER BY s.created_at DESC LIMIT ?""", (cap,)).fetchall():
        topic = r["topic"]
        rel = conn.execute(
            "SELECT COUNT(*) FROM scenarios").fetchone()[0]  # 전체 파급 수(재료 풍부도 힌트)
        made += _insert(
            conn, "report_suggest",
            f"'{topic}' — 내러티브·파급 재료가 쌓였습니다. 통합 리포트를 생성할까요?",
            f"이 주제에 파급 시나리오가 준비됐고 공유 인과로 엮인 내러티브가 있습니다(현재 파급 {rel}건). "
            "승인하면 다중 에이전트 리포트를 생성합니다 — opus 연쇄라 비용·시간(수 분)이 듭니다.",
            {"topic": topic, "narrative_version": r["narrative_version"]},
            f"report:{topic}:v{r['narrative_version']}")
    return made


def _bg_build_report(topic: str) -> None:
    """리포트 백그라운드 생성 — 승인 HTTP 응답을 막지 않도록 스레드에서(opus 연쇄 수 분)."""
    from pipeline.report import build_report
    conn = get_connection()
    try:
        build_report(conn, topic, force=False)
    except Exception:
        pass
    finally:
        conn.close()


def run_all(include_llm: bool = True) -> dict:
    """전체 스캔 배치 — LLM 0 kind는 항상, LLM 필요분(devils_advocate·vocab_merge)은 include_llm일 때만."""
    conn = get_connection()
    stats = {
        "neglect": scan_neglect(conn),
        "contested_edge": scan_contested_edges(conn),
        "falsifier_watch": scan_falsifier_watch(conn),
        "report_suggest": scan_report_suggestions(conn),
    }
    if include_llm:
        stats["devils_advocate"] = scan_devils_advocate(conn)
        # 노드 통합은 독립 작업 플래그·로그로 관리(관리자 페이지 가시성, D-055)
        import time as _time

        from pipeline.ops import flag_enabled, record_run
        if flag_enabled("vocab_merge"):
            t0 = _time.time()
            try:
                n = scan_vocab_merges(conn)
                stats["vocab_merge"] = n
                record_run("vocab_merge", "ok", f"병합 제안 {n}건", int((_time.time() - t0) * 1000))
            except Exception as e:  # noqa: BLE001 — 실패를 job_runs에 노출(삼키지 않음)
                stats["vocab_merge"] = f"error: {type(e).__name__}"
                record_run("vocab_merge", "error", f"{type(e).__name__}: {str(e)[:200]}",
                           int((_time.time() - t0) * 1000))
        else:
            record_run("vocab_merge", "skipped", "비활성(관리자 off)")
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
    elif kind == "report_suggest" and payload.get("topic"):
        import threading
        threading.Thread(target=_bg_build_report, args=(payload["topic"],), daemon=True).start()
        result = {"report": "생성 시작 — 수 분 후 리포트 탭에서 확인"}
    elif kind == "vocab_merge" and payload.get("survivor_id") and payload.get("loser_id"):
        from pipeline.vocab import merge_entities
        mc = get_connection()
        try:
            r = merge_entities(mc, payload["survivor_id"], payload["loser_id"], payload.get("rationale"))
            mc.commit()
            result = {"merged": True, "survivor": payload.get("survivor_name"),
                      "loser": payload.get("loser_name"), "detail": r}
        except Exception as e:  # noqa: BLE001
            result = {"merged": False, "error": str(e)[:150]}
        finally:
            mc.close()
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

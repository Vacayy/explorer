"""모순 감지 (K2) — 새 문서를 active 지식과 대조 (설계 프로세스 2, thesis_check의 일반화).

흐름 (일 1회 배치):
1. 미검사 최근 문서 × 느린 층(active) 지식 — 임베딩 유사 후보만 (비용 게이트)
2. haiku 단어 판정 SUPPORT/REFUTE/NEUTRAL (JSON 대신 토큰 — 형식 이탈에 강건)
3. 증거 부착: support→corroboration 증가(재활성화), refute→반박 축적
   독립성은 기존 증거와 릴레이 접기(RELAY_SIM)로 판별
4. 전환: 독립 반박 2+ → contested (재전환은 7일 쿨다운 — E-3)
   / observed가 독립 지지 2+ 얻으면 corroborated (승인 API와 같은 규칙)

contested는 삭제가 아니다 — ACH(Heuer)의 공존: 반박 증거가 붙은 채 소비 지점에서
가중만 낮아지고(EPISTEMIC_W), 홈 브리핑이 사람에게 판단을 넘긴다.
"""
import re
from datetime import datetime, timezone

from database import get_connection
from pipeline.consolidation import (RELAY_SIM, _cosine, _embed_statements,
                                    _embeddings, MIN_INDEPENDENT)

CANDIDATE_SIM = 0.50      # 문서-주장 임베딩 유사 후보 임계 (이하는 판정 스킵)
CONTESTED_COOLDOWN_D = 7  # 같은 지식 재전환 쿨다운 (E-3)
MAX_JUDGE = 40            # 배치당 haiku 판정 상한 (비용 게이트)
SCAN_WINDOW_DAYS = 7      # 검사 대상 문서 창


def _judge_stance(statement: str, doc_title: str, doc_text: str) -> str | None:
    """haiku 판정: 문서가 주장을 지지/반박/무관한가. 실패 시 None."""
    from pipeline.enrich import llm_engine, _call_claude_code
    if llm_engine() != "claude-code":
        return None
    prompt = (
        "투자 리서치 시스템이 축적한 [지식]과 새로 수집된 [문서]를 대조해라.\n"
        "- SUPPORT: 문서가 지식의 주장을 실질적으로 뒷받침하는 새 근거를 담고 있다\n"
        "- REFUTE: 문서가 지식의 주장과 반대되는 사실·전망·데이터를 담고 있다"
        " (단순 뉘앙스 차이는 아님 — 방향이 달라야 한다)\n"
        "- NEUTRAL: 관련은 있으나 지지도 반박도 아니다 / 판단 불가\n"
        "마지막 줄에 정확히 한 단어만: SUPPORT 또는 REFUTE 또는 NEUTRAL\n\n"
        f"[지식]\n{statement}\n\n[문서] {doc_title}\n{(doc_text or '')[:900]}"
    )
    try:
        raw = _call_claude_code(prompt)
        hits = re.findall(r"\b(SUPPORT|REFUTE|NEUTRAL)\b", raw)
        return hits[-1] if hits else None
    except Exception:
        return None


def _is_independent(conn, kid: int, doc_emb: list[float] | None) -> bool:
    """기존 증거 문서들과 릴레이 접기 — 유사 문서가 이미 있으면 비독립."""
    if not doc_emb:
        return True
    ev_docs = [r["doc_id"] for r in conn.execute(
        "SELECT doc_id FROM knowledge_evidence WHERE knowledge_id=? AND doc_id IS NOT NULL", (kid,))]
    embs = _embeddings(conn, ev_docs)
    return not any(_cosine(doc_emb, e) >= RELAY_SIM for e in embs.values())


def _counts(conn, kid: int) -> tuple[int, int]:
    """(독립 지지 수, 독립 반박 수)"""
    r = conn.execute("""
        SELECT SUM(stance='support' AND independent) s, SUM(stance='refute' AND independent) r
        FROM knowledge_evidence WHERE knowledge_id=?""", (kid,)).fetchone()
    return r["s"] or 0, r["r"] or 0


def ran_today(conn) -> bool:
    """오늘 스캔 흔적이 있으면 True — 30분 수집 체인 편승 시 일 1회 가드."""
    return bool(conn.execute(
        "SELECT 1 FROM knowledge_doc_scans WHERE date(scanned_at)=date('now') LIMIT 1").fetchone())


def scan_contradictions(max_judge: int = MAX_JUDGE) -> dict:
    """일 배치 — 미검사 최근 문서를 active 지식과 대조. 반환: 통계."""
    conn = get_connection()
    knowledge = conn.execute("""
        SELECT id, statement, epistemic_status, contested_at FROM knowledge
        WHERE review_status='active' AND valid_to IS NULL""").fetchall()
    if not knowledge:
        conn.close()
        return {"docs": 0, "judged": 0, "support": 0, "refute": 0, "contested": []}

    docs = conn.execute(f"""
        SELECT rd.id, rd.title, rd.published_at, substr(rd.markdown, 1, 1200) excerpt
        FROM raw_documents rd
        WHERE rd.published_at >= datetime('now', '-{SCAN_WINDOW_DAYS} days')
          AND rd.id NOT IN (SELECT doc_id FROM knowledge_doc_scans)
        ORDER BY rd.published_at DESC LIMIT 300""").fetchall()
    if not docs:
        conn.close()
        return {"docs": 0, "judged": 0, "support": 0, "refute": 0, "contested": []}

    k_embs = _embed_statements([k["statement"] for k in knowledge])
    d_embs = _embeddings(conn, [d["id"] for d in docs])

    stats = {"docs": len(docs), "judged": 0, "support": 0, "refute": 0, "contested": []}
    now = datetime.now(timezone.utc)
    for d in docs:
        if stats["judged"] >= max_judge:
            break  # 예산 소진 — 남은 문서는 미마킹, 다음 배치가 이어서
        de = d_embs.get(d["id"])
        exhausted = False
        if de:
            for k, ke in zip(knowledge, k_embs):
                if stats["judged"] >= max_judge:
                    exhausted = True  # 이 문서의 남은 대조가 잘림 — 다음 배치에서 재검
                    break
                if _cosine(de, ke) < CANDIDATE_SIM:
                    continue
                already = conn.execute(
                    "SELECT 1 FROM knowledge_evidence WHERE knowledge_id=? AND doc_id=?",
                    (k["id"], d["id"])).fetchone()
                if already:
                    continue
                stance = _judge_stance(k["statement"], d["title"] or "", d["excerpt"])
                stats["judged"] += 1
                if stance not in ("SUPPORT", "REFUTE"):
                    continue
                st = stance.lower()
                stats[st] += 1
                conn.execute("""
                    INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (k["id"], d["id"], st, int(_is_independent(conn, k["id"], de)),
                     d["published_at"] or now.isoformat()))
        if exhausted:
            break
        conn.execute("INSERT OR IGNORE INTO knowledge_doc_scans (doc_id) VALUES (?)", (d["id"],))
    conn.commit()

    # 전환 판정 — 증거가 새로 붙은 지식만 재평가
    for k in knowledge:
        sup, ref = _counts(conn, k["id"])
        if ref >= MIN_INDEPENDENT and k["epistemic_status"] != "contested":
            # 재전환 쿨다운 (E-3): contested_at이 7일 내면 조용히 유지
            if k["contested_at"] and (now - datetime.fromisoformat(
                    k["contested_at"])).days < CONTESTED_COOLDOWN_D:
                continue
            conn.execute("UPDATE knowledge SET epistemic_status='contested', contested_at=? WHERE id=?",
                         (now.isoformat(), k["id"]))
            stats["contested"].append(k["id"])
        elif k["epistemic_status"] == "observed" and sup >= MIN_INDEPENDENT:
            conn.execute("UPDATE knowledge SET epistemic_status='corroborated' WHERE id=?", (k["id"],))
    conn.commit()
    conn.close()
    return stats

"""반증 조건 감시 — "가설에는 틀렸다는 신호가 붙어야 한다" (지능 업그레이드 1).

배경 (docs/references 3문서의 공통 원리):
- 좋은 분석은 반증 조건 없이 끝나지 않는다 — 없으면 내러티브에 취약해진다
- K2 모순 감지는 범용(우연히 상충하는 문서를 잡음), 이것은 표적 감시:
  지식마다 관측 가능한 반증 신호 2~3개를 명시하고, 매일 그 신호를 검색한다

흐름:
1. 생성: 지식 승격/주입 시 haiku가 falsifier 2~3개 생성 (관측 가능해야 함)
2. 감시(일 1회): 미발화 falsifier마다 조건을 검색 → 최근 문서 후보 → haiku
   판정(TRIGGERED/NOT) — 조건 자체가 주장과 의미적으로 멀 수 있어서
   K2의 지식-문서 유사 매칭으로는 못 잡는 것을 잡는다
3. 발화: triggered 기록 + refute 증거 부착(릴레이 접기) → 기존 contested
   전환·홈 알림 기계가 이어받는다
"""
import json
import re
from datetime import datetime, timezone

from database import get_connection
from pipeline.consolidation import _embeddings, _cosine, RELAY_SIM

MAX_FALSIFIERS = 3
WATCH_DOC_DAYS = 2      # 일일 감시 창 (스캔 주기 1일 + 여유)
MAX_JUDGE_PER_RUN = 15  # 비용 게이트
SEARCH_TOP_K = 3
MIN_DOC_CHARS = 150     # 본문이 이보다 짧으면 판정 불가 (제목·링크만으로 오탐 — 실측)


def generate_falsifiers(conn, knowledge_id: int, statement: str) -> list[str]:
    """지식의 반증 조건 생성 — 이미 있으면 스킵 (멱등)."""
    if conn.execute("SELECT 1 FROM knowledge_falsifiers WHERE knowledge_id=?",
                    (knowledge_id,)).fetchone():
        return []
    from pipeline.enrich import llm_engine
    from pipeline.consolidation import _call_claude_knowledge
    if llm_engine() != "claude-code":
        return []
    prompt = (
        "다음 투자 관련 지식이 '틀렸다는 신호'를 2~3개 제시해라.\n"
        "규칙: 각 신호는 뉴스·리포트·데이터에서 관측 가능해야 한다 "
        "(예: '신규 팹 가동으로 공급 증가율이 수요 증가율을 상회', "
        "'주요 고객 CapEx 가이던스 하향'). 모호한 표현 금지.\n"
        'JSON만 출력: {"falsifiers": ["신호1", "신호2", ...]}\n\n'
        f"[지식]\n{statement}"
    )
    try:
        raw = _call_claude_knowledge(prompt)
        s, e = raw.find("{"), raw.rfind("}")
        items = json.loads(raw[s:e + 1]).get("falsifiers") or []
    except Exception:
        return []
    out = []
    for c in items[:MAX_FALSIFIERS]:
        c = str(c).strip()
        if len(c) < 8:
            continue
        conn.execute("INSERT INTO knowledge_falsifiers (knowledge_id, condition) VALUES (?, ?)",
                     (knowledge_id, c))
        out.append(c)
    conn.commit()
    return out


def _judge_triggered(condition: str, statement: str, doc_title: str, doc_text: str) -> bool:
    """haiku 판정: 문서가 반증 조건의 실제 발생을 보고하는가."""
    from pipeline.enrich import llm_engine
    from pipeline.consolidation import _call_claude_knowledge
    if llm_engine() != "claude-code":
        return False
    prompt = (
        "투자 지식에 대한 [반증 조건]이 [문서]에서 실제로 관측·보고되고 있는지 판정해라.\n"
        "- TRIGGERED: 문서가 조건에 해당하는 사실·데이터·전망을 구체적으로 담고 있다\n"
        "- NOT: 관련은 있어도 조건의 실제 발생 보고는 아니다 (가능성 언급만은 NOT, "
        "제목·링크뿐이거나 본문에 조건 관련 구체 내용이 없으면 반드시 NOT)\n"
        "마지막 줄에 정확히 한 단어만: TRIGGERED 또는 NOT\n\n"
        f"[지식] {statement}\n[반증 조건] {condition}\n\n"
        f"[문서] {doc_title}\n{(doc_text or '')[:900]}"
    )
    try:
        hits = re.findall(r"\b(TRIGGERED|NOT)\b", _call_claude_knowledge(prompt))
        return bool(hits) and hits[-1] == "TRIGGERED"
    except Exception:
        return False


def watch_falsifiers(max_judge: int = MAX_JUDGE_PER_RUN) -> dict:
    """일 배치 — 미발화 반증 조건을 최근 문서에서 표적 검색·판정."""
    from pipeline.search import search
    conn = get_connection()
    rows = conn.execute("""
        SELECT f.id, f.knowledge_id, f.condition, k.statement
        FROM knowledge_falsifiers f JOIN knowledge k ON k.id = f.knowledge_id
        WHERE f.triggered_at IS NULL AND k.review_status='active' AND k.valid_to IS NULL
    """).fetchall()
    stats = {"watched": len(rows), "judged": 0, "triggered": []}
    now = datetime.now(timezone.utc)
    for f in rows:
        if stats["judged"] >= max_judge:
            break
        try:
            hits = search(f["condition"], k=SEARCH_TOP_K)
        except Exception:
            continue
        for h in hits:
            if stats["judged"] >= max_judge:
                break
            doc = conn.execute(f"""
                SELECT id, title, published_at, substr(markdown,1,1200) ex FROM raw_documents
                WHERE id=? AND published_at >= datetime('now', '-{WATCH_DOC_DAYS} days')
                  AND length(markdown) >= {MIN_DOC_CHARS}
            """, (h["doc_id"],)).fetchone()
            if not doc:
                continue
            already = conn.execute(
                "SELECT 1 FROM knowledge_evidence WHERE knowledge_id=? AND doc_id=?",
                (f["knowledge_id"], doc["id"])).fetchone()
            if already:
                continue
            stats["judged"] += 1
            if not _judge_triggered(f["condition"], f["statement"], doc["title"] or "", doc["ex"]):
                continue
            # 발화: 기록 + refute 증거 부착 → contested 전환·알림은 기존 기계가
            conn.execute("UPDATE knowledge_falsifiers SET triggered_at=?, triggered_doc_id=? WHERE id=?",
                         (now.isoformat(), doc["id"], f["id"]))
            emb = _embeddings(conn, [doc["id"]]).get(doc["id"])
            ev_docs = [r["doc_id"] for r in conn.execute(
                "SELECT doc_id FROM knowledge_evidence WHERE knowledge_id=? AND doc_id IS NOT NULL",
                (f["knowledge_id"],))]
            independent = True
            if emb:
                embs = _embeddings(conn, ev_docs)
                independent = not any(_cosine(emb, e) >= RELAY_SIM for e in embs.values())
            conn.execute("""
                INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
                VALUES (?, ?, 'refute', ?, ?)""",
                (f["knowledge_id"], doc["id"], int(independent),
                 doc["published_at"] or now.isoformat()))
            stats["triggered"].append({"falsifier": f["condition"][:50], "doc": doc["id"]})
            break  # 이 조건은 발화됨 — 다음 조건으로
    conn.commit()
    conn.close()
    return stats


def backfill_falsifiers() -> dict:
    """기존 active 지식에 반증 조건 생성 (1회성)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, statement FROM knowledge
        WHERE review_status='active' AND valid_to IS NULL""").fetchall()
    made = 0
    for r in rows:
        made += len(generate_falsifiers(conn, r["id"], r["statement"]))
    conn.close()
    return {"knowledge": len(rows), "falsifiers": made}

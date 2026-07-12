"""세계관 브리핑 — 지식 계층의 종합 소비 (§G 통념 계량의 첫 표면).

"현재 투자자들이 보는 세계관은 이렇다" — 느린 층(승격 지식)이 뼈대,
빠른 층(이번 주 관측·신호)이 최신 변화. 3단 구조:
  ① 자리 잡은 전제 (corroborated, 구조/체제층 우선)
  ② 도전받는 것 (contested — 반박 요지 동반, ACH 공존)
  ③ 이번 주 달라진 것 (새 관측·진자·신호)

규율: 소스 도시에와 동일 — 게으른 생성 + inputs hash 가드, LLM은 열람 시에만.
모델: 종합이므로 sonnet (티어 분리 원칙 — 태깅=haiku, 종합=sonnet).
"""
import hashlib
import json
import os
import subprocess
import threading

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

WORLDVIEW_MODEL = os.getenv("WORLDVIEW_MODEL", "sonnet")
_lock = threading.Lock()


def gather(conn) -> dict:
    """재료 수집 — 전부 기존 데이터, LLM 0토큰."""
    knowledge = [dict(r) for r in conn.execute("""
        SELECT k.id, k.statement, k.epistemic_status, k.pace_layer,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id
                AND stance='support' AND independent=1) ind,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id
                AND stance='refute') ref
        FROM knowledge k
        WHERE k.review_status='active' AND k.valid_to IS NULL""")]
    for k in knowledge:
        if k["ref"]:
            k["refute_titles"] = [r["title"] for r in conn.execute("""
                SELECT rd.title FROM knowledge_evidence ev
                JOIN raw_documents rd ON rd.id = ev.doc_id
                WHERE ev.knowledge_id=? AND ev.stance='refute' LIMIT 3""", (k["id"],))]
    signals = [dict(r) for r in conn.execute("""
        SELECT s.signal_type, s.date, s.payload_json, e.name
        FROM signals s JOIN entities e ON e.id = s.entity_id
        WHERE s.date >= date('now', '-7 days')
          AND s.signal_type IN ('consensus_extreme', 'mention_surge', 'neglect')
        ORDER BY s.date DESC LIMIT 12""")]
    insights = [dict(r) for r in conn.execute("""
        SELECT e.name, d.insights, d.period_start
        FROM entity_digests d JOIN entities e ON e.id = d.entity_id
        WHERE d.insights IS NOT NULL AND d.period_start >= date('now', '-7 days')
        ORDER BY d.period_start DESC LIMIT 8""")]
    return {"knowledge": knowledge, "signals": signals, "insights": insights}


def inputs_hash(m: dict) -> str:
    parts = [f"k:{k['id']}:{k['epistemic_status']}:{k['ind']}:{k['ref']}" for k in m["knowledge"]]
    parts += [f"s:{s['signal_type']}:{s['name']}:{s['date']}" for s in m["signals"]]
    parts += [f"i:{i['name']}:{i['period_start']}" for i in m["insights"]]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def get_cached(conn):
    return conn.execute("""
        SELECT digest, doc_ids_hash, created_at FROM source_digests
        WHERE kind='worldview' AND key='global'""").fetchone()


LAYER_KO = {"event": "사건", "flow": "흐름", "cycle": "사이클", "structure": "구조", "regime": "체제"}


def _build_prompt(m: dict) -> str:
    kn_lines = []
    for k in sorted(m["knowledge"], key=lambda x: ("structure regime cycle flow event".split().index(x["pace_layer"])
                                                   if x["pace_layer"] in "structure regime cycle flow event".split() else 9)):
        line = (f"- [{LAYER_KO.get(k['pace_layer'], k['pace_layer'])}층 · {k['epistemic_status']} · "
                f"독립 관측 {k['ind']}건" + (f" · 반박 {k['ref']}건" if k["ref"] else "") + f"] {k['statement']}")
        if k.get("refute_titles"):
            line += "\n  반박 근거: " + " / ".join(k["refute_titles"])
        kn_lines.append(line)
    sig_lines = []
    for s in m["signals"]:
        p = json.loads(s["payload_json"] or "{}")
        if s["signal_type"] == "consensus_extreme":
            sig_lines.append(f"- {s['name']}: 감성 {'낙관' if p.get('direction')=='optimism' else '비관'} "
                             f"{round((p.get('ratio') or 0)*100)}% 일방향 (진자 극단)")
        elif s["signal_type"] == "mention_surge":
            sig_lines.append(f"- {s['name']}: 언급 급증 (7일 {p.get('count_7d')}회)")
        else:
            sig_lines.append(f"- {s['name']}: 소외 (PER {p.get('per')} · ROE {p.get('roe')}% · 무언급)")
    ins_lines = [f"- {i['name']}: {i['insights'][:150]}" for i in m["insights"]]

    return (
        "너는 1인 리서치센터의 센터장이다. 아래 재료로 '현재 시장 참여자들이 보는 세계관' "
        "브리핑을 써라. 재료는 시스템이 반복·독립 관측으로 승격한 지식(느린 층)과 "
        "이번 주 관측(빠른 층)이다.\n"
        "구조 (마크다운 ### 섹션 3개):\n"
        "1. '자리 잡은 전제' — 교차확인된(corroborated) 지식. 구조/체제층 먼저. "
        "독립 관측 수가 많을수록 통념에 가깝다 — 통념임을 명시해라.\n"
        "2. '도전받는 것' — contested 지식과 반박이 붙은 지식. 무엇이 주장이고 "
        "무엇이 반론인지 대비시켜라. 판단은 내리지 마라 — 갈등 자체가 정보다.\n"
        "3. '이번 주 달라진 것' — 새 관측·신호·진자. 세계관에 무엇이 새로 들어오려 하는지.\n"
        "규율: 재료에 없는 내용 금지. 각 주장 뒤에 (독립 N) 표기. 전체 500자 내외. "
        "마지막에 한 줄 — 이 세계관에서 가장 만장일치에 가까운 믿음 하나를 지목해라 "
        "(만장일치는 경고다).\n"
        'JSON만 출력: {"briefing": "마크다운"}\n\n'
        "[승격된 지식]\n" + "\n".join(kn_lines) +
        "\n\n[이번 주 신호]\n" + ("\n".join(sig_lines) or "- 없음") +
        "\n\n[이번 주 새 관측 (다이제스트 새로운 시각)]\n" + ("\n".join(ins_lines) or "- 없음")
    )


def _call_json_sonnet(prompt: str) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", WORLDVIEW_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def compute_worldview() -> dict:
    """hash가 바뀐 경우에만 sonnet 생성 — 아니면 캐시."""
    with _lock:
        conn = get_connection()
        m = gather(conn)
        if not m["knowledge"]:
            conn.close()
            return {"status": "empty", "briefing": None, "created_at": None}
        h = inputs_hash(m)
        cached = get_cached(conn)
        if cached and cached["doc_ids_hash"] == h:
            conn.close()
            return {"status": "cached", "briefing": cached["digest"], "created_at": cached["created_at"]}
        if llm_engine() != "claude-code":
            conn.close()
            return {"status": "unavailable",
                    "briefing": cached["digest"] if cached else None,
                    "created_at": cached["created_at"] if cached else None}
        try:
            data = _call_json_sonnet(_build_prompt(m))
        except Exception:
            conn.close()
            return {"status": "failed",
                    "briefing": cached["digest"] if cached else None,
                    "created_at": cached["created_at"] if cached else None}
        conn.execute("""
            INSERT INTO source_digests (kind, key, digest, doc_count, doc_ids_hash, model, created_at)
            VALUES ('worldview', 'global', ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(kind, key) DO UPDATE SET
                digest=excluded.digest, doc_count=excluded.doc_count,
                doc_ids_hash=excluded.doc_ids_hash, model=excluded.model,
                created_at=excluded.created_at
        """, (data.get("briefing"), len(m["knowledge"]), h, f"claude-code/{WORLDVIEW_MODEL}"))
        conn.commit()
        row = get_cached(conn)
        conn.close()
        return {"status": "fresh", "briefing": row["digest"], "created_at": row["created_at"]}

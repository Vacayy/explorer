"""사건 시나리오 엔진 — 사건을 그대로 받아들이지 않고 파급 체인으로 푼다.

"호르무즈 통제 → 유조선 통행 어려움 → 조달 비율 → 유가 상승 → 쇼티지 →
가격 자극" — 사건의 1차·2차·3차 파급을 인과 체인으로 전개하고, 각 단계를
근거(수집 문서 인용 vs 일반지식 구분)와 확률 감각, 감시 조건과 함께 제시.

입구: 대화에서 "시나리오: <사건>" (기억해:와 같은 인터셉트 패턴).
결과의 감시 조건은 '기억해:'로 주입하면 반증 센티넬이 이어받는다.
모델: 종합이므로 sonnet (티어 분리 원칙).
"""
import json
import os
import subprocess

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

SCENARIO_MODEL = os.getenv("SCENARIO_MODEL", "opus")  # 심층 종합 티어 — 다단 인과 추론
SCENARIO_PREFIXES = ("시나리오:", "시나리오 :", "만약:", "what if:")
TOP_DOCS = 10
EXCERPT = 800


def parse_scenario(text: str) -> str | None:
    q = (text or "").strip()
    for p in SCENARIO_PREFIXES:
        if q.lower().startswith(p):
            event = q[len(p):].strip()
            return event or None
    return None


def _build_prompt(event: str, docs: list[dict], knowledge: list[dict]) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] ({d['source_type']}, {(d['published_at'] or '')[:10]}) {d['title']}\n{d['excerpt']}"
        for i, d in enumerate(docs)) or "(관련 수집 문서 없음)"
    from pipeline.knowledge_recall import knowledge_block
    kn = knowledge_block(knowledge, "승격된 지식 — 시스템이 검증한 전제")
    return (
        "너는 사건의 파급을 추론하는 투자 리서치 전략가다. 아래 [사건]을 그대로 받아들이지 말고 "
        "인과 체인으로 전개해라.\n"
        'JSON만 출력: {"scenario": "마크다운"}\n'
        "마크다운 구조 (섹션 고정):\n"
        "### 사건 정의 — 무엇이 실제로 일어났고/일어난다고 가정하며, 무엇은 아직 불확실한가\n"
        "### 파급 체인 — '사건 → 1차 → 2차 → 3차' 화살표 체인을 먼저 한 줄로, 이어서 단계별로:\n"
        "  각 단계마다 ①메커니즘 ②정량 단서(수집 문서 근거면 [번호] 인용, 일반지식이면 '(일반지식)' 표기) "
        "③단계 확률 감각(높음/중간/낮음 + 이유). 확률은 뒤 단계로 갈수록 곱으로 낮아진다는 걸 명시해라\n"
        "### 영향 지도 — 수혜/피해 자산·섹터·종목 (한국 시장 관점 포함)\n"
        "### 감시 조건 — 이 시나리오가 '진행 중'임을 알리는 관측 가능한 신호 3개와 "
        "'기각'을 알리는 신호 2개\n"
        "### 반대 시나리오 — 이 체인이 통째로 틀리는 가장 그럴듯한 경로 한 단락 (ACH — 확증 방지)\n"
        "규칙: 수집 문서에 없는 수치는 (일반지식)으로 정직하게 표기. 과장 금지, 각 단계는 "
        "반증 가능한 서술로. 전체 700자 내외.\n\n"
        f"[사건]\n{event}\n"
        f"{kn}\n\n[수집 문서]\n{ctx}"
    )


def build_scenario(event: str) -> dict:
    """사건 → 파급 체인 시나리오. 반환: rag.ask와 같은 형태 (answer/citations/model)."""
    if llm_engine() != "claude-code":
        return {"error": "LLM 엔진 없음 (ENRICH_ENGINE=claude-code 필요)"}
    from pipeline.search import search
    from pipeline.knowledge_recall import recall_for_query
    from pipeline.visibility import get_muted, is_muted

    hits = search(event, k=TOP_DOCS + 5)
    conn = get_connection()
    muted = get_muted(conn)
    docs = []
    for h in hits:
        d = conn.execute(f"""
            SELECT id, source_type, source_id, title, url, published_at,
                   substr(markdown, 1, {EXCERPT}) excerpt
            FROM raw_documents WHERE id=?""", (h["doc_id"],)).fetchone()
        if d and not is_muted(d["source_type"], d["source_id"] or "", d["url"], muted):
            docs.append(dict(d))
        if len(docs) >= TOP_DOCS:
            break
    knowledge = recall_for_query(conn, event)
    conn.close()

    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", SCENARIO_MODEL, "--output-format", "json",
         _build_prompt(event, docs, knowledge)],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    md = json.loads(raw[s:e + 1]).get("scenario") or ""
    md += ("\n\n---\n*감시 조건 중 계속 지켜볼 것이 있으면 `기억해: <조건>`으로 주입하세요 — "
           "반증 센티넬이 매일 감시합니다.*")
    return {
        "answer": md,
        "citations": [{"n": i + 1, "doc_id": d["id"], "title": d["title"], "url": d["url"],
                       "source_type": d["source_type"], "published_at": d["published_at"]}
                      for i, d in enumerate(docs)],
        "gaps": [],
        "model": f"claude-code/{SCENARIO_MODEL}",
    }

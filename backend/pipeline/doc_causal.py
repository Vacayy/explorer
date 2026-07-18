"""문서 레벨 인과 추출 — 제2 인과 공급원 (D-028 레버 3, docs/specs/doc-causal-extraction.md).

내러티브(종합)와 독립된 공급원: 인사이트 밀도 높은 단일 문서에서 인과 엣지를 직접 추출해
같은 그래프에 적재(source_doc_id, narrative_id=NULL). 같은 고리가 양쪽에서 나오면 기존
upsert가 confidence를 강화 — 교차검증이 실제로 작동하기 시작한다.

노이즈 방어: 선별(LLM 태깅 완료 + 본문 1,200자+) · 명시 인과만(프롬프트 규율) ·
낮은 초기 confidence 상한(0.5).
"""
import json
import os
import subprocess

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine
from pipeline.narrative import _node_vocab, _persist_causal

DOC_CAUSAL_MODEL = os.getenv("DOC_CAUSAL_MODEL", "sonnet")
MIN_DOC_CHARS = 1200      # 짧은 시황 코멘트 배제 — 인과 서술이 있을 만한 밀도
EXCERPT = 3000
CONF_CAP = 0.5            # 문서 1건의 주장은 낮게 시작 — 반복 확인돼야 커진다


def _build_prompt(title: str, markdown: str, node_vocab: list[str]) -> str:
    return (
        "너는 투자 리서치의 인과 구조 추출가다. 아래 문서에서 **명시적으로 서술된** 인과관계만 "
        "구조화해라. 문서에 없는 인과를 추론·보완하지 마라. 명확한 인과 서술이 없으면 빈 배열.\n"
        "★투자·시장 세계관에 속하는 인과만: 거시경제·산업·기업·정책·시장 구조가 대상이다. "
        "지역 행정·생활 정보·사회 일반 등 투자 판단과 무관한 인과는 문서에 서술돼 있어도 제외.\n"
        'JSON만 출력: {"causal": {"nodes": [{"name","type"}], "edges": '
        '[{"from","to","rel","mechanism","orientation","reference_period","confidence"}]}}\n'
        "규칙 (내러티브 인과 추출과 동일):\n"
        "- type ∈ company·sector·theme·person·macro(유가·금리·인플레)·policy(협상·규제)·event(봉쇄·사고)\n"
        f"- ★기존 노드가 있으면 새로 만들지 말고 정확히 그 이름을 재사용: {', '.join(node_vocab[:60])}\n"
        "- rel='CAUSES'(원인→결과). 수혜 섹터는 rel='BENEFITS_FROM'(from=수혜 섹터, to=동인). "
        "수혜 종착은 sector까지만 — 개별 종목 금지.\n"
        "- 행위자: 특정 인물의 선언·비전·자본배분이나 특정 기업의 결정이 메커니즘의 실체라면 "
        "person/company 노드로 명시 ('그 사람/기업이 사라지면 이 인과가 약해지는가' 기준).\n"
        "- 피드백(자기강화)을 발견하면 시점이 다른 두 엣지로 펴서 표현 (같은 시점 내 순환 금지).\n"
        "- orientation ∈ past|current|forward. reference_period: 이 인과가 작동하는 시점(예 '2026 하반기'), "
        "모르면 null. confidence: 0~1 — 문서가 단정하면 0.5, 조건부/추측이면 0.3.\n"
        f"[문서]\n제목: {title}\n{(markdown or '')[:EXCERPT]}"
    )


def _call(prompt: str) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", DOC_CAUSAL_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {(proc.stdout or proc.stderr)[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def _candidates(conn, limit: int) -> list[dict]:
    """추출 후보 — LLM 태깅 완료 + 본문 충분 + 아직 시도 안 함, 최신순."""
    return [dict(r) for r in conn.execute(f"""
        SELECT rd.id, rd.title, rd.markdown
        FROM raw_documents rd JOIN enrichments en ON en.doc_id = rd.id
        WHERE en.model != 'keyword' AND en.causal_extracted_at IS NULL
          AND length(rd.markdown) >= {MIN_DOC_CHARS}
        ORDER BY rd.published_at DESC LIMIT ?""", (limit,)).fetchall()]


def extract_doc_causal(limit: int = 20) -> dict:
    """배치 — 후보 문서에서 인과 추출·적재. 시도는 성공/0건 무관하게 기록(재시도 방지)."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    conn = get_connection()
    docs = _candidates(conn, limit)
    stats = {"docs": len(docs), "edges": 0, "empty": 0, "failed": 0}
    vocab = _node_vocab(conn)
    for d in docs:
        try:
            data = _call(_build_prompt(d["title"] or "", d["markdown"] or "", vocab))
        except Exception:
            stats["failed"] += 1
            continue  # 실패는 기록하지 않음 — 다음 실행에서 재시도
        causal = data.get("causal") or {}
        made = _persist_causal(conn, None, d["id"], causal, conf_cap=CONF_CAP)
        if made == 0 and not (causal.get("edges") or []):
            stats["empty"] += 1
        stats["edges"] += made
        conn.execute("UPDATE enrichments SET causal_extracted_at=datetime('now') WHERE doc_id=?",
                     (d["id"],))
        conn.commit()
    conn.close()
    return stats

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
from pipeline.narrative import GEO_VOCAB

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


def _build_prompt(event: str, docs: list[dict], knowledge: list[dict],
                   node_vocab: list[str]) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] ({d['source_type']}, {(d['published_at'] or '')[:10]}) {d['title']}\n{d['excerpt']}"
        for i, d in enumerate(docs)) or "(관련 수집 문서 없음)"
    from pipeline.knowledge_recall import knowledge_block
    from pipeline.lenses import LENS_WORLDVIEW
    kn = knowledge_block(knowledge, "승격된 지식 — 시스템이 검증한 전제")
    return (
        "너는 사건의 파급을 추론하는 투자 리서치 전략가다. 아래 [사건]을 그대로 받아들이지 말고 "
        "인과 체인으로 전개해 결과를 JSON으로 정리해라. (설명·머리말 없이 JSON만, 코드블록 없이.)\n"
        'JSON만 출력: {"scenario": "마크다운", "beneficiaries": [{"name","rel","reason"}], '
        '"causal": {"nodes": [{"name","type","layer"}], '
        '"edges": [{"from","to","rel","mechanism","orientation","reference_period","geo","confidence"}]}}\n'
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
        "★수혜/피해 종목 (별도 필드 beneficiaries) — 위 파급 논리로 실제 영향받는 한국 상장 개별 종목을 "
        "직접 지목해라. 문서에 자주 언급됐는지가 아니라 인과 논리로 판단(아직 회자 안 됐어도 논리상 수혜면 지목). "
        "각 원소 {name: 정확한 상장사명, rel: '수혜'|'피해', reason: 이 파급 체인에서 왜 수혜/피해인지 한 문장}. "
        "논리로 근거 댈 수 있는 것만, 억지 지목 금지. 최대 6개.\n\n"
        "★인과 그래프 추출 (본문과 별도로 — 위 파급 체인을 노드·엣지로, 내러티브 인과와 동일 규약):\n"
        "- nodes: {\"name\",\"type\",\"layer\"}, type ∈ company·sector·theme·person·macro·policy·event, "
        "layer ∈ event·flow·cycle·structure·regime (느릴수록 구조적)\n"
        f"  ★기존 노드가 있으면 새로 만들지 말고 정확히 그 이름을 재사용: {', '.join(node_vocab[:60])}\n"
        "- edges: rel='CAUSES'(원인→결과), 수혜 섹터는 rel='BENEFITS_FROM'(from=수혜 섹터, to=동인). "
        "수혜 종착은 sector까지만 — 개별 종목 금지. 특정 인물/기업의 결정이 메커니즘의 실체면 "
        "person/company 노드로 명시('사라지면 약해지는가' 기준). 피드백은 시점 다른 두 엣지로. "
        "orientation ∈ past|current|forward, reference_period는 작동 시점(모르면 null), "
        f"geo ∈ {{{GEO_VOCAB}}} 중 하나(특정 지역 사건이면 해당국, 전세계 공통이면 글로벌, 목록 밖이면 기타, 모르면 null), "
        "confidence 0~1(가정된 사건에서 출발하므로 보수적으로).\n\n"
        f"[사건]\n{event}\n"
        f"\n{LENS_WORLDVIEW}\n"
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
    from pipeline.narrative import _node_vocab, _persist_causal
    vocab = _node_vocab(conn)
    conn.close()

    # opus는 결과를 ```json 펜스로 감싸거나 긴 출력이 절단될 수 있어 파싱이 간헐 실패 → 1회 재시도.
    prompt = _build_prompt(event, docs, knowledge, vocab)
    data, last_err = None, ""
    for _ in range(2):
        proc = subprocess.run(
            [_claude_bin(), "-p", "--model", SCENARIO_MODEL, "--output-format", "json", prompt],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            last_err = f"rc={proc.returncode} {proc.stderr[:120]}"
            continue
        try:
            raw = json.loads(proc.stdout).get("result", "")
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s < 0 or e <= s:
                last_err = f"JSON 없음: {raw[:80]!r}"
                continue
            data = json.loads(raw[s:e + 1])
            break
        except Exception as ex:  # noqa: BLE001 — 절단·형식 오류 모두 재시도
            last_err = f"{type(ex).__name__}: {str(ex)[:100]}"
    if data is None:
        raise RuntimeError(f"scenario 파싱 실패(2회): {last_err}")
    md = data.get("scenario") or ""

    # 논리 기반 수혜 종목 (D-035 통합 체인) — opus가 파급 논리로 지목한 종목을 resolve + RS·밸류 enrich.
    # 공동언급 스크린과 달리 '아직 회자 안 됐어도 논리상 수혜'를 잡는다 (말뭉치 최신편향 탈출).
    beneficiaries: list[dict] = []
    picks = data.get("beneficiaries") or []
    if isinstance(picks, list) and picks:
        from pipeline.beneficiary import resolve_and_enrich
        conn = get_connection()
        try:
            beneficiaries = resolve_and_enrich(conn, [p for p in picks if isinstance(p, dict)])
        finally:
            conn.close()

    # 인과 그래프 물질화 (D-028 제3 공급원) — 시나리오 파급 체인도 같은 그래프에 적재.
    # 가정된 사건에서 출발하므로 confidence 상한은 문서 레벨과 같은 0.5.
    if data.get("causal"):
        conn = get_connection()
        try:
            _persist_causal(conn, None, docs[0]["id"] if docs else None,
                            data["causal"], conf_cap=0.5)
            conn.commit()
        finally:
            conn.close()
    md += ("\n\n---\n*감시 조건 중 계속 지켜볼 것이 있으면 `기억해: <조건>`으로 주입하세요 — "
           "반증 센티넬이 매일 감시합니다.*")
    return {
        "answer": md,
        "beneficiaries": beneficiaries,
        "citations": [{"n": i + 1, "doc_id": d["id"], "title": d["title"], "url": d["url"],
                       "source_type": d["source_type"], "published_at": d["published_at"]}
                      for i, d in enumerate(docs)],
        "gaps": [],
        "model": f"claude-code/{SCENARIO_MODEL}",
    }

"""정전(canon) 지식층 — 사람+Claude가 정리한 통사 노트를 흡수하고 역사 인과를 추출 (D-030).

vault/canon/*.md → raw_documents(source_type='canon') → 역사 인과 체인 추출(opus).
canon 인과의 차이 (doc_causal과 대비):
- epistemic_type='observed' — 시장 가설(hypothesis)보다 강한 '널리 수용된 역사 해석'
- confidence 상한 0.85 — 높지만 fact(1.0)는 아님
- reference_period = 역사적 시점(2001, 2011…) — 그래프의 시간 지평을 과거로 확장
- 모델 = opus — 다단 역사 인과의 정확한 시점·방향 판정 (소량이라 비용 무관)
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from config import VAULT_PATH
from database import get_connection
from pipeline.base import RawDoc
from pipeline.enrich import _claude_bin, llm_engine
from pipeline.narrative import _node_vocab, _persist_causal

CANON_MODEL = os.getenv("CANON_MODEL", "opus")
CANON_DIR = VAULT_PATH / "canon"
CONF_CAP = 0.85
EXCERPT = 12000   # canon 노트는 통째로 (밀도 높은 정리본이라 자르면 사슬이 끊긴다)


def ingest_canon() -> dict:
    """vault/canon/*.md → 척추 흡수 (source_type='canon', 파일명=자연키, 멱등)."""
    from pipeline.store import store_document
    stats = {"stored": 0, "unchanged": 0}
    if not CANON_DIR.exists():
        return stats
    for p in sorted(CANON_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("# ")),
                     p.stem)
        r = store_document(RawDoc(
            source_type="canon", source_id=p.stem, title=title,
            published_at=datetime.now(timezone.utc).isoformat(), raw_content=text, kind="text"))
        stats["stored" if r.get("status") != "unchanged" else "unchanged"] += 1
    return stats


def _build_prompt(title: str, markdown: str, node_vocab: list[str]) -> str:
    return (
        "너는 역사 인과 구조 추출가다. 아래는 널리 수용된 역사적 사실과 통설적 해석을 정리한 "
        "정전(canon) 노트다. 여기 서술된 인과 사슬을 구조화해라 — 노트에 없는 인과를 추론으로 "
        "보태지 마라.\n"
        'JSON만 출력: {"causal": {"nodes": [{"name","type","layer"}], "edges": '
        '[{"from","to","rel","mechanism","orientation","reference_period","effect_direction","effect_strength","confidence"}]}}\n'
        "규칙:\n"
        "- type ∈ company·sector·theme·person·macro·policy·event\n"
        "- layer ∈ event·flow·cycle·structure·regime — 역사 노트이므로 structure·regime이 많을 것\n"
        f"- ★기존 노드가 있으면 새로 만들지 말고 정확히 그 이름을 재사용: {', '.join(node_vocab[:60])}\n"
        "  특히 사슬의 현재 끝이 기존 노드(예: '세계질서 재편', 'AI 수출통제')로 이어지도록 — "
        "역사가 현재 그래프에 뿌리를 대는 것이 목적이다.\n"
        "- rel='CAUSES'. ★reference_period: 각 인과가 작동한 **역사적 시점을 반드시 명시** "
        "(예: '2001', '2011', '2018', '2022'). orientation은 대부분 past, 현재 진행분만 current.\n"
        "- 행위자: 특정 인물·기업·기관의 결정이 메커니즘의 실체면 person/company 노드로.\n"
        "- 피드백(자기강화 — 예: 수출통제→자립 투자→견제 강화)은 시점이 다른 두 엣지로 펴서.\n"
        "- mechanism: 한 문장, 노트의 서술에 근거. effect_direction ∈ positive|negative|mixed. "
        "effect_strength ∈ unknown|weak|moderate|strong (효과 크기 — 확신과 별개 축, 숫자 금지, 애매하면 낮은 쪽). "
        "confidence: 통설적 합의 강도 (0.6~0.85).\n"
        f"[canon 노트]\n제목: {title}\n{(markdown or '')[:EXCERPT]}"
    )


def _call(prompt: str) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--setting-sources", "", "--tools", "", "--model", CANON_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {(proc.stdout or proc.stderr)[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def extract_canon_causal() -> dict:
    """canon 문서의 역사 인과 추출·적재 — causal_extracted_at 미기록분만 (멱등)."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    conn = get_connection()
    docs = [dict(r) for r in conn.execute("""
        SELECT rd.id, rd.title, rd.markdown
        FROM raw_documents rd JOIN enrichments en ON en.doc_id = rd.id
        WHERE rd.source_type='canon' AND en.causal_extracted_at IS NULL""").fetchall()]
    stats = {"docs": len(docs), "edges": 0, "failed": 0}
    vocab = _node_vocab(conn)
    for d in docs:
        try:
            data = _call(_build_prompt(d["title"] or "", d["markdown"] or "", vocab))
        except Exception:
            stats["failed"] += 1
            continue
        made = _persist_causal(conn, None, d["id"], data.get("causal") or {},
                               conf_cap=CONF_CAP, epistemic="observed")
        stats["edges"] += made
        conn.execute("UPDATE enrichments SET causal_extracted_at=datetime('now') WHERE doc_id=?",
                     (d["id"],))
        conn.commit()
    conn.close()
    return stats

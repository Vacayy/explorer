"""기존 인과 그래프 노드의 pace_layer 백필 — haiku 배치 (D-030 Layer 0).

프롬프트가 layer를 뽑기 시작한 건 D-030부터라 기존 800+ 노드는 미태깅.
노드명 40개/콜 haiku 분류 (좁은 분류 작업 — 상위 티어 불필요). 멱등(태깅된 노드 skip).

사용법: python scripts/backfill_pace_layer.py
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import _claude_bin, llm_engine

BATCH = 40
LAYERS = ("event", "flow", "cycle", "structure", "regime")


def classify_batch(names: list[str]) -> dict[str, str]:
    prompt = (
        "다음은 투자 인과 그래프의 노드 이름들이다. 각각을 시간 지속성 층으로 분류해 JSON만 출력.\n"
        "layer ∈ event(단발 사건: 봉쇄·발표·급락) | flow(수급·자금 흐름) | cycle(사이클 국면: "
        "가격·재고·업황) | structure(경쟁구도·계약·산업구조·기술 아키텍처) | regime(제도·패러다임·"
        "시대적 힘: 패권 경쟁·AI 전환·인구구조)\n"
        '형식: {"layers": {"노드명": "layer", ...}} — 모든 노드 포함.\n'
        f"노드들: {json.dumps(names, ensure_ascii=False)}"
    )
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "haiku", "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {(proc.stdout or proc.stderr)[:150]}")
    raw = json.loads(proc.stdout).get("result", "")
    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    return {k: v for k, v in (data.get("layers") or {}).items() if v in LAYERS}


def main():
    init_db()
    if llm_engine() != "claude-code":
        print("claude-code 엔진 필요")
        sys.exit(1)
    conn = get_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT DISTINCT e.id, e.name, e.meta_json FROM entities e
        WHERE e.id IN (SELECT src_id FROM entity_relations WHERE rel_type IN ('CAUSES','BENEFITS_FROM')
                       UNION SELECT dst_id FROM entity_relations WHERE rel_type IN ('CAUSES','BENEFITS_FROM'))
    """).fetchall()]
    todo = []
    for r in rows:
        meta = json.loads(r["meta_json"]) if r["meta_json"] else {}
        if not meta.get("pace_layer"):
            todo.append(r)
    print(f"대상: {len(todo)}/{len(rows)} 노드 (배치 {BATCH}개/콜)")

    ok = failed = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            layers = classify_batch([b["name"] for b in batch])
        except Exception as e:
            failed += len(batch)
            print(f"  배치 실패 (재실행 시 재시도): {str(e)[:100]}")
            continue
        for b in batch:
            layer = layers.get(b["name"])
            if not layer:
                continue
            meta = json.loads(b["meta_json"]) if b["meta_json"] else {}
            meta["pace_layer"] = layer
            conn.execute("UPDATE entities SET meta_json=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), b["id"]))
            ok += 1
        conn.commit()
        print(f"  진행 {min(i + BATCH, len(todo))}/{len(todo)} (적용 {ok})", flush=True)
    conn.close()
    print(f"완료: 적용 {ok} / 실패 {failed}")


if __name__ == "__main__":
    main()

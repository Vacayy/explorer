"""어휘 통합 배치 (vocab consolidation, D-033) — theme·macro 노드 파편화 치유.

기본 = dry-run: 후보 생성(fastembed) → 판정(sonnet) → 병합 계획을 사람이 검토 가능한
목록으로 출력하고 JSON으로 저장. --apply는 저장된 계획의 same 판정만 적용(LLM 재호출 없음).

승인 모델(D-020 "기계는 제안, 사람은 승인"): dry-run으로 계획을 검토한 뒤에만 --apply.

사용법:
  python scripts/consolidate_vocab.py                 # dry-run (계획 생성·저장)
  python scripts/consolidate_vocab.py --apply         # 저장된 계획의 same만 병합
  python scripts/consolidate_vocab.py --threshold 0.92 --types theme,macro
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import llm_engine
from pipeline.vocab import (
    find_merge_candidates, judge_pairs, merge_entities, pick_survivor,
)

DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "logs" / "vocab_merge_plan.json"


def _corroborated_count(conn) -> int:
    """2+ 독립 내러티브가 주장한 인과 엣지 수 (효과 지표)."""
    return conn.execute("""
        SELECT COUNT(*) c FROM (
            SELECT entity_relation_id FROM narrative_edge_evidence
            GROUP BY entity_relation_id HAVING COUNT(DISTINCT narrative_id) >= 2)
    """).fetchone()["c"]


def run_dry(threshold: float, types: tuple, plan_path: Path) -> None:
    conn = get_connection()
    result = find_merge_candidates(conn, types=types, threshold=threshold)
    candidates = result["candidates"]
    if result["reason"]:
        print(f"[후보 생성] {result['reason']}")
    print(f"[후보] type={','.join(types)} threshold={threshold} → {len(candidates)}쌍")
    if not candidates:
        conn.close()
        return
    if llm_engine() != "claude-code":
        print("판정 불가 — .env ENRICH_ENGINE=claude-code 필요. 후보만 출력하고 종료.")
        for c in candidates:
            print(f"  [{c['type']}] {c['a_name']} ~ {c['b_name']}  (cos={c['cosine']})")
        conn.close()
        return

    judged = judge_pairs(candidates)
    merges, rejected = [], []
    for j in judged:
        if j["verdict"] == "same":
            survivor_id, loser_id = pick_survivor(conn, j["a_id"], j["b_id"])
            names = {j["a_id"]: j["a_name"], j["b_id"]: j["b_name"]}
            merges.append({
                "survivor_id": survivor_id, "survivor_name": names[survivor_id],
                "loser_id": loser_id, "loser_name": names[loser_id],
                "type": j["type"], "cosine": j["cosine"], "rationale": j["rationale"],
            })
        else:
            rejected.append(j)

    print(f"[판정] same {len(merges)}쌍 / different {len(rejected)}쌍")
    print("\n=== 병합 계획 (survivor ← loser) ===")
    for m in merges:
        print(f"  [{m['type']}] {m['survivor_name']} ← {m['loser_name']}  "
              f"(cos={m['cosine']}) — {m['rationale']}")
    if rejected:
        print("\n=== 기각 (different — 병합 안 함) ===")
        for r in rejected:
            print(f"  [{r['type']}] {r['a_name']} ≠ {r['b_name']}  "
                  f"(cos={r['cosine']}) — {r['rationale']}")

    plan = {"threshold": threshold, "types": list(types),
            "merges": merges, "rejected": rejected}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[계획 저장] {plan_path}  (검토 후 --apply 로 same {len(merges)}쌍 적용)")
    print(f"[현재] corroborated_by(2+) 엣지 {_corroborated_count(conn)}개")
    conn.close()


def run_apply(plan_path: Path) -> None:
    if not plan_path.exists():
        print(f"계획 파일 없음: {plan_path} — 먼저 dry-run 실행")
        sys.exit(1)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    merges = plan.get("merges") or []
    if not merges:
        print("계획에 same(병합) 쌍이 없음.")
        return
    conn = get_connection()
    before = _corroborated_count(conn)

    # 연쇄 병합 안전: 이미 loser로 사라진 id는 survivor로 이어붙여 재해소
    redirect: dict[int, int] = {}

    def resolve(eid: int) -> int:
        while eid in redirect:
            eid = redirect[eid]
        return eid

    applied = 0
    for m in merges:
        s, l = resolve(m["survivor_id"]), resolve(m["loser_id"])
        if s == l:
            continue
        res = merge_entities(conn, s, l, m["rationale"])
        if res["status"] == "merged":
            redirect[l] = s
            applied += 1
            print(f"  병합: {m['survivor_name']} ← {m['loser_name']}")
        else:
            print(f"  건너뜀: {m['loser_name']} ({res.get('reason')})")

    after = _corroborated_count(conn)
    conn.close()
    print(f"\n[적용 완료] {applied}쌍 병합")
    print(f"[corroborated_by(2+) 엣지] {before} → {after}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="저장된 계획의 same 판정 적용 (기본=dry-run)")
    ap.add_argument("--threshold", type=float, default=0.90)
    ap.add_argument("--types", type=str, default="theme,macro,sector")  # D-062: sector 추가
    ap.add_argument("--plan", type=str, default=str(DEFAULT_PLAN))
    args = ap.parse_args()

    init_db()
    plan_path = Path(args.plan)
    if args.apply:
        run_apply(plan_path)
    else:
        types = tuple(t.strip() for t in args.types.split(",") if t.strip())
        run_dry(args.threshold, types, plan_path)


if __name__ == "__main__":
    main()

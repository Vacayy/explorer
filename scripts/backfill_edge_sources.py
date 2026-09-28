"""D-204 백필: 기존 인과 엣지의 출처 상태를 분류한다. 기본은 dry-run(집계만), --apply로 적용.

- canon(epistemic observed)·문서 단위 추출(출처 문서에 causal_extracted_at) → 'document' (출처 유지)
- 시나리오 생성 시각(±300초)에 만들어진 엣지 → 'scenario' (출처 칸 비움)
- 내러티브 생성 시각(±5초)에 만들어졌거나 출처를 알 수 없는 엣지 → 'legacy_unverified' (출처 칸 비움)
비우는 source_doc_id는 legacy_source_doc_id에 보존한다(되돌리기: UPDATE ... SET source_doc_id=legacy_source_doc_id).
이미 source_status가 있는 엣지(D-204 이후 생성)는 건드리지 않는다. 적용 전에 DB 백업을 확보할 것.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection  # noqa: E402

BASE = "er.rel_type IN ('CAUSES','BENEFITS_FROM') AND er.source_status IS NULL"
NARR = "EXISTS (SELECT 1 FROM narratives n WHERE abs(julianday(er.created_at)-julianday(n.created_at))*86400 < 5)"
SCEN = "EXISTS (SELECT 1 FROM scenarios s WHERE abs(julianday(er.created_at)-julianday(s.created_at))*86400 <= 300)"
DOC = "EXISTS (SELECT 1 FROM enrichments en WHERE en.doc_id=er.source_doc_id AND en.causal_extracted_at IS NOT NULL)"

RULES = [  # 순서대로, 앞 규칙에 걸린 엣지는 뒤에서 다시 보지 않는다
    ("document", "canon", f"er.epistemic_type='observed'", False),
    ("document", "doc_causal", f"NOT {NARR} AND {DOC}", False),
    ("scenario", "scenario", f"NOT {NARR} AND {SCEN}", True),
    ("legacy_unverified", "narrative_or_unknown", "1=1", True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_connection()
    total, earlier = 0, []
    for status, name, cond, clear in RULES:
        # 앞 규칙에 걸린 엣지는 제외 — dry-run에서도 적용 후와 같은 집계가 나오게
        where = f"{BASE} AND ({cond})" + "".join(f" AND NOT ({c})" for c in earlier)
        earlier.append(cond)
        n = conn.execute(f"SELECT COUNT(*) FROM entity_relations er WHERE {where}").fetchone()[0]
        total += n
        print(f"{name:<22} → {status:<18} {n:>6}{'  (출처 칸 비움, legacy 보존)' if clear else ''}")
        if args.apply and n:
            ids = f"SELECT er.id FROM entity_relations er WHERE {where}"
            conn.execute(f"UPDATE entity_relations SET legacy_source_doc_id=COALESCE(legacy_source_doc_id, source_doc_id) WHERE id IN ({ids})")
            if clear:
                conn.execute(f"UPDATE entity_relations SET source_status=?, source_doc_id=NULL WHERE id IN ({ids})", (status,))
            else:
                conn.execute(f"UPDATE entity_relations SET source_status=? WHERE id IN ({ids})", (status,))
    if args.apply:
        conn.commit()
    print(f"합계 {total} · {'적용함' if args.apply else 'dry-run(--apply로 적용)'}")
    conn.close()


if __name__ == "__main__":
    main()

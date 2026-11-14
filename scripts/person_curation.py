"""인물 이름 자동 정리·역할 분류·메모 저자 연결 — 한 번 돌리기 (ia-redesign §4.23 1단계).

소프트 병합이다: 진 쪽 엔티티를 지우지 않고 status='merged' + entity_merges(old_entity_id·prev_status)로 잇는다.
멱등이다. 주간 정리(auto_curation.run_curation)가 플래그 `person_curation`(기본 on) 아래에서 같은 일을 한다.

배포 순서: DB 백업 → 백엔드 재시작(init_db가 entity_merges 칼럼·person_roles 표를 만든다) → --dry-run 확인 → 적용.

사용법:
  python scripts/person_curation.py --dry-run          # 묶을 이름·그대로 둔 이름·역할 분포만 출력, 쓰기 없음
  python scripts/person_curation.py                    # 적용
  python scripts/person_curation.py --split 13605      # 묶은 이름 하나 되돌리기(다음 정리에서 다시 묶지 않는다)
  python scripts/person_curation.py --db /path/copy.db --dry-run --json out.json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import DB_PATH
from pipeline import people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="계획만 출력하고 쓰지 않는다")
    ap.add_argument("--split", type=int, help="묶은 이름(진 쪽 엔티티 id) 하나를 되돌린다")
    ap.add_argument("--db", default=str(DB_PATH), help=f"DB 경로 (기본: {DB_PATH})")
    ap.add_argument("--json", help="계획 전체를 이 파일에 JSON으로")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if not any(r[1] == "old_entity_id" for r in conn.execute("PRAGMA table_info(entity_merges)")):
            sys.exit("entity_merges.old_entity_id 칼럼이 없습니다. 백엔드를 한 번 띄우거나 database.init_db()를 먼저 실행하세요.")
        if args.split:
            print("되돌림" if people.split(conn, args.split) else "되돌릴 병합이 없습니다")
            return
        plan = people.plan(conn)
        if args.json:
            Path(args.json).write_text(json.dumps(plan, ensure_ascii=False, indent=1))
        out = people.curate(conn, apply_changes=not args.dry_run)
    finally:
        conn.close()
    s = plan["stats"]
    print(f"{'드라이런' if args.dry_run else '적용'} — 인물 엔티티 {s['people']} · 묶을 사람 {s['groups']} · 묶을 이름 {s['names']}")
    print("  규칙별:", ", ".join(f"{people.RULE_KO[k]} {v}" for k, v in sorted(s["by_rule"].items(), key=lambda kv: -kv[1])))
    print("  그대로 둔 이름:", s["held"], s["held_by_reason"])
    for g in plan["groups"][:15]:
        print(f"  {g['survivor_name']} ← " + " · ".join(f"{m['name']}({people.RULE_KO[m['rule']]})" for m in g["members"]))
    print("  메모 저자:", out["authors"])
    print("  역할:", out["roles"])
    if "merge" in out:
        print("  병합 결과:", out["merge"])


if __name__ == "__main__":
    main()

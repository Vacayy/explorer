"""레거시 `watchlist` → 기본 관심 묶음('관심 종목', stock_groups) 이관 (docs/specs/portfolio-watch.md, D-185).

멱등이다. 묶음에 없는 종목은 확신도·목표가·논지와 함께 넣고, 이미 있는 종목은 묶음 쪽 빈 칸만 레거시 값으로 채운다.
`watchlist` 테이블은 지우지 않는다. 논지 원문은 출력하지 않는다(길이만).

사용법:
  python scripts/migrate_watchlist_to_groups.py --dry-run              # 계획만 출력, 쓰기 없음
  python scripts/migrate_watchlist_to_groups.py                        # 적용
  python scripts/migrate_watchlist_to_groups.py --db /path/copy.db --dry-run
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import DB_PATH
from pipeline.watch_rules import migrate_watchlist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="계획만 출력하고 쓰지 않는다")
    ap.add_argument("--db", default=str(DB_PATH), help=f"DB 경로 (기본: {DB_PATH})")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        plan = migrate_watchlist(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    head = "DRY-RUN" if args.dry_run else "APPLIED"
    group = "새로 만듦" if plan["create_group"] else f"id={plan['group_id']}"
    print(f"[{head}] 기본 관심 묶음 {group} · 레거시 {plan['legacy']}건 → 추가 {len(plan['add'])} · 빈 칸 채움 {len(plan['fill'])} · 그대로 {len(plan['same'])}")
    for key, label in (("add", "추가"), ("fill", "채움")):
        for item in plan[key]:
            print(f"  {label} {item['stock_code']} {item['name']}" + (f" ({', '.join(item['fields'])})" if item["fields"] else ""))
    if plan["group_only"]:
        print(f"  묶음에만 있음(유지) {len(plan['group_only'])}: {', '.join(plan['group_only'])}")


if __name__ == "__main__":
    main()

"""홈 '종목 추적' 위젯(옛 원천) → 기본 관심 묶음의 추적 표시(새 원천) 복사 (ia-redesign §10.2 ②, D-293).

멱등이다. 위젯 종목이 관심 종목에 없으면 추적 표시와 함께 넣고, 있으면 추적 표시만 켠다.
위젯·home_boards는 지우지 않고, 새 원천에만 있는 추적 표시도 끄지 않는다.

배포 순서(필수): 추적이 새 원천만 읽는 커밋(개편 3d)을 배포하기 **전에** 이 스크립트를 실행한다.
그 커밋부터 stock_tracker.tracked_codes는 위젯을 읽지 않아, 이관하지 않은 위젯 종목은 알림이 소리 없이 멈춘다.

사용법:
  python scripts/migrate_tracking_to_groups.py --dry-run              # 계획만 출력, 쓰기 없음
  python scripts/migrate_tracking_to_groups.py                        # 적용
  python scripts/migrate_tracking_to_groups.py --db /path/copy.db --dry-run
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import DB_PATH
from pipeline.stock_tracker import member_codes, migrate_widget_tracking, source_diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="계획만 출력하고 쓰지 않는다")
    ap.add_argument("--db", default=str(DB_PATH), help=f"DB 경로 (기본: {DB_PATH})")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if not any(r[1] == "tracked" for r in conn.execute("PRAGMA table_info(stock_group_members)")):
            sys.exit("stock_group_members.tracked 컬럼이 없습니다. 백엔드를 한 번 띄우거나 database.init_db()를 먼저 실행하세요.")
        before = member_codes(conn)
        plan = migrate_widget_tracking(conn, dry_run=args.dry_run)
        after = member_codes(conn)
        diff = source_diff(conn)
    finally:
        conn.close()
    head = "DRY-RUN" if args.dry_run else "APPLIED"
    group = "새로 만듦" if plan["create_group"] else f"id={plan['group_id']}"
    print(f"[{head}] 기본 관심 묶음 {group} · 위젯 종목 → 추가 {len(plan['add'])} · 추적 표시 켬 {len(plan['mark'])} · 이미 추적 {len(plan['same'])}")
    for key, label in (("add", "관심 종목에 추가+추적"), ("mark", "추적 표시 켬"), ("same", "그대로")):
        for item in plan[key]:
            print(f"  {label} {item['stock_code']} {item['name']}")
    print(f"  추적 표시 전 {before}")
    print(f"  추적 표시 후 {after}")
    print(f"  홈 위젯에만(이관 누락 — 알림이 멈춤) {diff['widget_only'] or '-'} · 추적 표시에만 {diff['member_only'] or '-'}")


if __name__ == "__main__":
    main()

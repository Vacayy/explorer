"""아침 브리핑 텔레그램 발송 (cron: 평일 08:00 KST).

  python scripts/send_briefing.py            # 발송 (토큰 미설정이면 skip)
  python scripts/send_briefing.py --dry-run  # 메시지 미리보기만
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.notify import push_briefing

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    init_db()
    print("[briefing-push]", push_briefing(dry_run=args.dry_run))

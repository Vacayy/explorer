"""아침 브리핑 텔레그램 발송 (launchd: 평일 07:00 KST, dev.explorer.briefing).

  python scripts/send_briefing.py            # 발송 (토큰 미설정이면 skip)
  python scripts/send_briefing.py --dry-run  # 메시지 미리보기만
  python scripts/send_briefing.py --catch-up # 미발송이면 발송 (30분 체인이 호출, 멱등)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.notify import ensure_briefing_sent, push_briefing

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--catch-up", action="store_true",
                        help="오늘 미발송일 때만 발송 (체인 편승용)")
    args = parser.parse_args()
    init_db()
    if args.catch_up:
        print("[briefing-catchup]", ensure_briefing_sent())
    else:
        print("[briefing-push]", push_briefing(dry_run=args.dry_run))

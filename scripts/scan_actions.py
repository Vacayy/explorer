"""기업활동 스캔 실행 — 기본 최근 3일 (cron 체인용, 멱등).

  python scripts/scan_actions.py            # 최근 3일
  python scripts/scan_actions.py --days 30  # 백필
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.actions import scan, summarize_pending

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    init_db()
    end = date.today()
    bgn = end - timedelta(days=args.days)
    print("[scan-actions]", scan(bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d")))
    print("[summarize]", summarize_pending())

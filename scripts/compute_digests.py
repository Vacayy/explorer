"""언급 다이제스트 계산 (1D + 롤링 7D). cron 체인에서 주기 실행 — hash 가드로 대부분 no-op.

  python scripts/compute_digests.py                 # 오늘 (KST)
  python scripts/compute_digests.py --backfill 7    # 지난 N일 1D 백필 + 7D
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.digests import compute_daily, compute_rolling7

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=0)
    args = parser.parse_args()
    init_db()
    if args.backfill:
        for i in range(args.backfill, 0, -1):
            d = (date.today() - timedelta(days=i - 1)).isoformat()
            print(f"[daily {d}]", compute_daily(d))
    else:
        print("[daily]", compute_daily())
    print("[rolling7]", compute_rolling7())

"""언급 다이제스트 계산 (1D 오늘 + 1W 이번 주). cron 체인 주기 실행 — hash 가드로 대부분 no-op.

  python scripts/compute_digests.py                 # 오늘(1D) + 이번 주(1W)
  python scripts/compute_digests.py --backfill 7    # 지난 N일 1D 백필
과거 월(1M)·소급은 종목 진입 시 catch_up(D-085)이 담당 — cron은 최신만.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.digests import compute_daily, compute_weekly

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=0)
    args = parser.parse_args()
    init_db()
    from pipeline.ops import run_job

    def _work():
        if args.backfill:
            for i in range(args.backfill, 0, -1):
                d = (date.today() - timedelta(days=i - 1)).isoformat()
                print(f"[daily {d}]", compute_daily(d))
            return {"backfill": args.backfill}
        daily = compute_daily()
        weekly = compute_weekly()   # 이번 주(월~일), 이번 주 언급 종목 전체
        print("[daily]", daily, "[weekly]", weekly)
        return {"daily_gen": daily.get("generated", 0) if isinstance(daily, dict) else 0}
    run_job("compute_digests", _work)   # 관리자 플래그 게이트 + 로그 (D-055)

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
        # **닫힌 구간만** 생성한다 (D-124). 전엔 진행 중인 오늘·이번 주를 대상으로 삼아,
        # 그 구간에 새 문서가 들어올 때마다 doc_ids_hash가 바뀌어 같은 요약을 다시 썼다
        # (실측: 1d start=08-31이 46건, 같은 종목이 7일간 7회 재생성).
        # 닫힌 구간은 문서 집합이 고정이라 첫 생성 뒤 해시가 일치 → unchanged로 LLM 0.
        # 진행 중 구간이 필요하면 종목 진입 시 catch_up(D-085)이 채운다.
        today = date.today()
        y = (today - timedelta(days=1)).isoformat()                    # 어제(확정)
        last_mon = today - timedelta(days=today.weekday() + 7)         # 지난 주 월요일(확정)
        daily = compute_daily(y)
        weekly = compute_weekly(last_mon.isoformat())
        print(f"[daily {y}]", daily, f"[weekly {last_mon}]", weekly)
        return {"daily_gen": daily.get("generated", 0) if isinstance(daily, dict) else 0,
                "weekly_gen": weekly.get("generated", 0) if isinstance(weekly, dict) else 0}
    run_job("compute_digests", _work)   # 관리자 플래그 게이트 + 로그 (D-055)

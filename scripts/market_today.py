"""Market Today 회차 생성 (docs/specs/market-today.md) — launchd `markettoday` 평일 10:00·13:00·15:40.

  python scripts/market_today.py                       # 지금 시점의 회차(가장 최근에 지난 시각)
  python scripts/market_today.py --date 2026-11-03 --slot 1300 [--force]
결과는 job_runs('market_today')에 ok / skipped(주말·휴장·자료 부족) / error로 남는다.
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import record_run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--slot", default=None, choices=["1000", "1300", "1540"])
    ap.add_argument("--force", action="store_true", help="이미 만든 회차도 다시")
    a = ap.parse_args()
    init_db()
    from pipeline import market_today as mt
    started = time.time()
    day = date.fromisoformat(a.date) if a.date else None
    if (day is None) != (a.slot is None):
        print("--date와 --slot은 함께 준다")
        return 2
    r = mt.run(day, a.slot, force=a.force)
    print(r)
    status = {"ok": "ok", "exists": "skipped", "skipped": "skipped"}.get(r["status"], "error")
    summary = " · ".join(f"{k} {v}" for k, v in r.items() if k != "status")
    record_run("market_today", status, f"{r['status']} · {summary}"[:500], int((time.time() - started) * 1000))
    return 0 if status != "error" else 1


if __name__ == "__main__":
    sys.exit(main())

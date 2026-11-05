"""Market Today 회차 생성 (docs/specs/market-today.md) — launchd `markettoday` 평일 09:30·11:30·15:00·16:00(마감 정리).

  python scripts/market_today.py                       # 지금 시점의 회차(가장 최근에 지난 시각)
  python scripts/market_today.py --date 2026-11-03 --slot 1130 [--force]
결과는 job_runs('market_today')에 ok / skipped(주말·휴장·자료 부족) / error로 남는다.
16:00 마감 정리가 만들어지면 이번 주 큰 그림 조건 실행을 이어서 판정한다(weekly_big_picture --event와 같음).
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
    ap.add_argument("--slot", default=None, choices=["0930", "1130", "1500", "1600"])
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
    if r["status"] == "ok" and r.get("slot") == mt.WRAP_SLOT:
        _big_picture_event()
    return 0 if status != "error" else 1


def _big_picture_event() -> None:
    """16:00 마감 정리 뒤 — 지난 큰 그림 생성 이후 새 내러티브 버전 3편 이상이고 오늘 생성 시도가 없을 때만 한 번 더(D-313 4).
    판정·기록은 weekly_big_picture가 한다. 실패해도 Market Today 회차 결과는 바꾸지 않는다."""
    try:
        from pipeline.weekly_big_picture import run as big_picture
        print("[big-picture]", big_picture("event"))
    except Exception as e:  # noqa: BLE001
        print(f"[big-picture] event 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())

"""국내 실적 시즌 지난 시즌 메우기 — 수동 1회 (pipeline/kr_season.backfill, ia-redesign §4.22).

전 시장 공시 목록 수집(krcompany ①)이 2026-09-11부터라 그 전 시즌의 잠정실적은 보유·관심·시총 상위 기업 것만 있다.
시즌마다 공정공시(I002)·유가/코스닥 목록만 받아 채운다(시즌 하나에 DART 호출 20회 안팎). 다 받은 시즌은 다시 받지 않는다.

  python scripts/backfill_kr_season.py 2026Q2 2026Q1 2025Q4 2025Q3
  python scripts/backfill_kr_season.py 2026Q2 --budget 60
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db


def main() -> int:
    from config import DART_API_KEY
    from pipeline import kr_company_data as kr
    from pipeline.kr_season import backfill, backfilled

    ap = argparse.ArgumentParser()
    ap.add_argument("seasons", nargs="+", help="시즌 키(예: 2026Q2)")
    ap.add_argument("--budget", type=int, default=200)
    args = ap.parse_args()

    init_db()
    client = kr.DartClient(DART_API_KEY, args.budget)
    conn = get_connection()
    failed = False
    try:
        for key in args.seasons:
            if backfilled(key):
                print(f"[{key}] 이미 메움 — 건너뜀")
                continue
            try:
                r = backfill(conn, client, key)
            except (kr.BudgetExhausted, kr.DartFatal) as e:
                print(f"[{key}] 중단: {type(e).__name__} {e}")
                failed = True
                break
            print(f"[{key}]", r)
            failed = failed or bool(r["failed"])
    finally:
        conn.close()
    print(f"[backfill_kr_season] DART 호출 {client.calls}/{args.budget}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

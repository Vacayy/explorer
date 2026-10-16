"""회사채 스프레드 수집 (D-230, docs/specs/credit-spreads.md) — launchd `credit` 매일 07:30.

국채 곡선(FRED) → 회사별 대표 채권(주 1회 재선정) → 이력. 채권 데이터는 로컬 어댑터(git 제외)가 제공하고,
없으면 job_runs에 skipped로 남긴다. 모델 호출 0.

  python scripts/collect_credit.py                 # 전체
  python scripts/collect_credit.py --tickers ORCL,META
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db  # noqa: E402
from pipeline import credit_spreads as cs  # noqa: E402
from pipeline.ops import record_run, run_job  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=None)
    args = ap.parse_args()
    init_db()
    if cs.source() is None:
        record_run("credit", "skipped", "로컬 데이터 원천 어댑터 없음")
        print("[credit] 로컬 데이터 원천 어댑터가 없어 건너뜁니다.")
        return

    def job():
        conn = get_connection()
        try:
            r = cs.collect(conn, tickers=args.tickers.split(",") if args.tickers else None)
        finally:
            conn.close()
        print(f"[credit] {r}")
        return {"ok": r["ok"], "failed": len(r["failed"]), "resolved": r["resolved"], "first_fail": (r["failed"] or [""])[0]}
    run_job("credit", job)


if __name__ == "__main__":
    main()

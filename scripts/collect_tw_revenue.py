"""대만 월매출 수집 (docs/specs/tw-revenue.md) — 91개사, LLM 0.

  python scripts/collect_tw_revenue.py               # 최신 월(TWSE·TPEx Open API) — launchd twrevenue 매일
  python scripts/collect_tw_revenue.py --backfill 36 # 과거 36개월(MOPS 월별 요약, 있는 달은 건너뜀)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import run_job  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--require", default="", help="쉼표 구분 코드 — 이 회사들이 빠진 달은 다시 받는다(새 대상 과거분)")
    args = ap.parse_args()
    init_db()
    from pipeline import tw_revenue

    def work():
        req = {c.strip() for c in args.require.split(",") if c.strip()} or None
        r = tw_revenue.backfill(args.backfill, require=req) if args.backfill else tw_revenue.fetch_latest()
        print(f"[tw_revenue] {r}", flush=True)
        return r

    r = run_job("tw_revenue", work)
    return 1 if isinstance(r, dict) and r.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

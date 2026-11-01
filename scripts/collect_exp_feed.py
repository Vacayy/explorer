"""피드 증권사 전망 추출 (docs/specs/value-chain.md §15 3단계) — 피드 문서의 증권사·리서치·회사 가이던스 전망 → 전망 원장. LLM(haiku).

  python scripts/collect_exp_feed.py              # launchd expfeed 매일 12:00 — 최근 3일, 상한 25건
  python scripts/collect_exp_feed.py --backfill   # 최근 60일, 상한 100건
관리자 스위치: feature_flags 'exp_feed'(run_job이 off면 건너뛰고 기록). 한 문서는 한 번만 처리한다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import run_job  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    init_db()
    from pipeline.exp_feed import collect

    def work():
        r = collect(backfill=args.backfill)
        print(f"[exp_feed] {r}", flush=True)
        return r

    r = run_job("exp_feed", work)
    return 1 if isinstance(r, dict) and r.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

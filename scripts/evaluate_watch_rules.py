"""종목 묶음 감시 규칙 일일 평가 (docs/specs/portfolio-watch.md, D-185).

launchd `dev.explorer.watch`가 평일 16:40에 실행한다. 모델 호출 없이 순수 계산이며, 같은 기준일은 다시 평가하지 않는다.

사용법:
  python scripts/evaluate_watch_rules.py                 # 최신 저장 시세일 기준
  python scripts/evaluate_watch_rules.py --as-of 2026-09-18
  python scripts/evaluate_watch_rules.py --force         # 같은 기준일도 다시 계산
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.watch_rules import evaluate_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="기준일 YYYY-MM-DD (기본: 최신 저장 시세일)")
    ap.add_argument("--force", action="store_true", help="같은 기준일도 다시 평가")
    args = ap.parse_args()
    init_db()
    summary = evaluate_all(args.as_of, args.force)
    print(" · ".join(f"{k} {v}" for k, v in summary.items()))


if __name__ == "__main__":
    main()

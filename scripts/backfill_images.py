"""이미지 해석 백로그 — 30분 체인에서 회차마다 조금씩 (pipeline/image_backfill.py).

사용법:
  python scripts/backfill_images.py --dry-run          # 대상 문서·호출 수만
  python scripts/backfill_images.py --calls 200 --minutes 8
관리자 플래그 image_backfill로 끄고 켠다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=200)
    parser.add_argument("--minutes", type=float, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    init_db()
    from pipeline.image_backfill import run
    if args.dry_run:
        print("[backfill-images]", run(dry_run=True))
    else:
        from pipeline.ops import run_job
        r = run_job("image_backfill", lambda: run(calls=args.calls, minutes=args.minutes))
        if r is not None:                # None = 플래그 off (run_job이 이미 안내 출력)
            print("[backfill-images]", r)

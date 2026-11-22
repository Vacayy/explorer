"""이미지 해석 복구 — 맥미니 수집분 중 해석 없이 게시된 문서 (pipeline/image_recovery.py).

사용법:
  python scripts/recover_images.py --images 2 --dry-run          # 대상과 필요한 해석 수만
  python scripts/recover_images.py --images 2 --ids 100029462     # 지정 문서만
  python scripts/recover_images.py --reconcile                    # 실패 회차의 미게시 본문을 projection으로 되돌림
관리자 플래그 image_recovery로 끄고 켠다.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=int, default=2, help="이번 회차에 읽을 이미지 수 상한")
    parser.add_argument("--minutes", type=float, default=8)
    parser.add_argument("--ids", default="", help="쉼표로 구분한 문서 ID (없으면 맥미니 대역의 미처리 문서)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    init_db()
    from pipeline import image_recovery
    if args.reconcile:
        print("[recover-images]", json.dumps(image_recovery.reconcile(), ensure_ascii=False))
        sys.exit(0)
    # 시험 회차는 작업 경로가 넘겨 준 문서만 (refactor_collect_engine FORWARDED)
    ids = [int(x) for x in (args.ids or os.environ.get("COLLECT_IMAGE_RECOVERY_IDS", "")).split(",") if x.strip()] or None
    if args.dry_run:
        print("[recover-images]", json.dumps(image_recovery.run(images=args.images, ids=ids, dry_run=True), ensure_ascii=False))
    else:
        from pipeline.ops import run_job
        r = run_job(image_recovery.JOB, lambda: image_recovery.run(images=args.images, minutes=args.minutes, ids=ids))
        if r is not None:                # None = 플래그 off (run_job이 이미 안내 출력)
            print("[recover-images]", json.dumps(r, ensure_ascii=False))

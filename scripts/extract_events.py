"""이미지 비전 분석 → 증시일정 이벤트 추출 (cron 체인에서 주기 실행).

미분석 이미지만 처리하므로 재실행 안전. 이미지당 ~7초 (claude-code haiku).

**관리자 플래그 게이트(D-116)**: 미분석 이미지가 ~2,000장 쌓여 있어 회당 40장씩
갈아먹는 구조다 — 다른 무거운 잡들과 같이 feature_flags로 on/off 되게 했다(D-055 패턴).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    init_db()
    from pipeline.ops import run_job
    from pipeline.vision import extract_events
    r = run_job("extract_events", lambda: extract_events(limit=args.limit))
    if r is not None:                    # None = 플래그 off (run_job이 이미 안내 출력)
        print("[extract-events]", r)

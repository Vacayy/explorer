"""이미지 비전 분석 → 증시일정 이벤트 추출 (cron 체인에서 주기 실행).

미분석 이미지만 처리하므로 재실행 안전. 이미지당 ~7초 (claude-code haiku).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.vision import extract_events

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    init_db()
    print("[extract-events]", extract_events(limit=args.limit))

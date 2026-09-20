#!/usr/bin/env python3
"""Prepare a blind expert rubric; optionally generate a same-evidence baseline."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pipeline.weekly.evaluation import build_packet
from pipeline.weekly.store import Store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--baseline", action="store_true", help="같은 읽은 자료로 추가 LLM 1회 호출")
    ap.add_argument("--model")
    ap.add_argument("--reference-manifest", type=Path, help="평가 전용 원문/차트 보존 manifest. 기준선 모델 입력에서는 제외")
    args = ap.parse_args()
    print(build_packet(Store(), args.run_id, baseline=args.baseline, model=args.model, reference_manifest=args.reference_manifest))


if __name__ == "__main__":
    main()

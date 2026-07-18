"""문서 레벨 인과 추출 배치 (D-028 레버 3) — 제2 인과 공급원.

사용법: python scripts/extract_doc_causal.py [--limit N]   # 기본 20, 수동 백필은 크게
cron 편입은 보류(체인 런타임) — docs/specs/doc-causal-extraction.md §3.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.doc_causal import extract_doc_causal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    init_db()
    print("[doc-causal]", extract_doc_causal(limit=args.limit))


if __name__ == "__main__":
    main()

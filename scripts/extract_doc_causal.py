"""문서 레벨 인과 추출 배치 (D-028 레버 3) — 제2 인과 공급원.

사용법: python scripts/extract_doc_causal.py [--limit N]   # cron 기본 15, 수동 백필은 크게
**cron 체인 편입됨(D-088)** — 모든 소스(feed·컨콜)의 새 문서가 enrich 후 인과 엣지로 추출된다.
멱등(causal_extracted_at 마커), 관리자 플래그 게이트(run_job). docs/specs/doc-causal-extraction.md.
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
    from pipeline.ops import run_job

    def _work():
        r = extract_doc_causal(limit=args.limit)
        print("[doc-causal]", r)
        return r
    run_job("extract_doc_causal", _work)   # 플래그 게이트 + job_runs 로그 (D-055)


if __name__ == "__main__":
    main()

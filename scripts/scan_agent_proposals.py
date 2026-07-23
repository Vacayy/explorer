"""에이전트 제안함 스캔 배치 (주 1회) — 시스템이 스스로 조사거리를 포착해 승인 큐로.

kind 4종: neglect·contested_edge·falsifier_watch(LLM 0) + devils_advocate(haiku).
사용법: python scripts/scan_agent_proposals.py [--no-llm]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.agent_proposals import run_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="devils_advocate(haiku) 생략")
    args = parser.parse_args()
    init_db()
    from pipeline.ops import run_job

    def _work():
        r = run_all(include_llm=not args.no_llm)
        print("[agent-proposals]", r)
        return r
    run_job("agent_proposals", _work)   # 관리자 플래그 게이트 + 로그 (D-055)


if __name__ == "__main__":
    main()

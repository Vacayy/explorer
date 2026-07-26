"""핵심질문 트래커 일 1회 갱신 (D-067·D-068·D-069) — cron 편입.

자동도출(지배 내러티브→제안 큐) + 관측 갱신(numeric 컨콜·sentiment 코퍼스) + 전 추적 질문 재판정.
event-driven 편승: 새 재료 없으면 멱등 스킵으로 사실상 no-op. 관리자 플래그 게이트(D-055).

사용법: python scripts/refresh_questions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.questions import refresh_all


def main():
    init_db()
    from pipeline.ops import run_job

    def _work():
        r = refresh_all()
        print("[refresh_questions]", r)
        return r
    run_job("refresh_questions", _work)


if __name__ == "__main__":
    main()

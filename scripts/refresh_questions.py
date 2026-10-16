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
    _portfolio_thesis_alert()
    _watch_reason_alert()


def _portfolio_thesis_alert():
    """보유 종목 논지 판정이 나빠졌으면 텔레그램(portfolio-intelligence §2). 실패는 job_runs에 남긴다."""
    import time
    from pipeline import portfolio as pf, portfolio_thesis as pt
    from pipeline.ops import record_run
    started = time.time()
    conn = pf.connect()
    try:
        holdings = pf.summary(conn)["holdings"]
        n = pt.alert(conn, holdings) if holdings else 0
        record_run("pf_thesis", "ok", f"sent {n}", int((time.time() - started) * 1000))
    except Exception as e:  # noqa: BLE001
        record_run("pf_thesis", "error", f"{type(e).__name__}: {str(e)[:200]}", int((time.time() - started) * 1000))
    finally:
        conn.close()



def _watch_reason_alert():
    """관심 종목 이유 판정이 어느 쪽으로든 기울면 텔레그램(portfolio-intelligence §6, D-227). 실패는 job_runs에."""
    import time
    from pipeline import portfolio as pf, watch_reasons as wr
    from pipeline.ops import record_run
    started = time.time()
    conn = pf.connect()
    try:
        members = wr.watch_members(conn)
        n = wr.alert(conn, members) if members else 0
        record_run("watch_reason", "ok", f"sent {n}", int((time.time() - started) * 1000))
    except Exception as e:  # noqa: BLE001
        record_run("watch_reason", "error", f"{type(e).__name__}: {str(e)[:200]}", int((time.time() - started) * 1000))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

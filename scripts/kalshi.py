"""Kalshi 예측시장 인기 이벤트 수집 (backend/pipeline/kalshi.py) — launchd `kalshi` 매일 08:00·16:00·23:00 KST.

  python scripts/kalshi.py
결과는 job_runs('kalshi')에 ok / error로 남는다(카테고리 일부 실패는 ok + 요약에 실패 카테고리).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import record_run  # noqa: E402


def main() -> int:
    init_db()
    from pipeline import kalshi
    started = time.time()
    try:
        r = kalshi.collect()
    except Exception as e:  # noqa: BLE001
        r = {"status": "error", "events": 0, "degraded": [f"{type(e).__name__}: {str(e)[:160]}"]}
    print(r)
    summary = f"{r['status']} · 이벤트 {r['events']}" + (f" · 실패 {'; '.join(r['degraded'])}" if r["degraded"] else "")
    record_run("kalshi", r["status"], summary[:500], int((time.time() - started) * 1000))
    return 0 if r["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

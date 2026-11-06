"""지수 장중 5분 경로 수집 (backend/pipeline/index_intraday.py) — launchd `indexintraday` 10분마다.

  python scripts/index_intraday.py               # 지금 장이 열린 시장만(장 밖이면 외부 호출 없이 끝)
  python scripts/index_intraday.py --backfill    # 국장·미장 둘 다 최근 5거래일(수동)
결과는 job_runs('index_intraday')에 ok / error로만 남긴다(장 밖·휴장 skipped는 10분마다 쌓지 않는다).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import record_run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="국장·미장 최근 5거래일")
    a = ap.parse_args()
    from pipeline import index_intraday as ii
    markets = list(ii.SESSIONS) if a.backfill else ii.due_markets()
    if not markets:
        return 0
    init_db()
    started = time.time()
    r = ii.collect(markets, period="5d" if a.backfill else "1d")
    print(r)
    status = r["status"]
    if status != "skipped":
        summary = f"{r['status']} · {','.join(r.get('markets', []))} · {r['rows']}행" + (f" · 실패 {', '.join(r['degraded'])}" if r.get("degraded") else "")
        record_run("index_intraday", status, summary, int((time.time() - started) * 1000))
    return 0 if status != "error" else 1


if __name__ == "__main__":
    sys.exit(main())

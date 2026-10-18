"""미국 수요 기업 분기 실적 수집 (docs/specs/value-chain.md §6) — SEC XBRL companyfacts, LLM 0.
고객 집중도(us_customers, §12)는 주 1회, 시장 기대치 스냅샷(vc_expectations, §15)은 매일 함께 돈다.

  python scripts/collect_us_fundamentals.py   # launchd usfund 매일 08:10 (실적 발표 뒤 10-Q가 올라오면 반영)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402,F401 — .env(SEC_USER_AGENT)
from database import init_db  # noqa: E402
from pipeline.ops import run_job  # noqa: E402


def main() -> int:
    init_db()
    from pipeline.us_fundamentals import collect

    def work():
        r = collect()
        print(f"[us_fundamentals] {r}", flush=True)
        return r

    r = run_job("us_fundamentals", work)
    # 고객 집중도는 10-K/10-Q 주석이라 분기에 한 번 바뀐다 — 공시 원본을 티커당 7건 읽어 무거우므로 주 1회만
    from database import get_connection
    conn = get_connection()
    last = conn.execute("SELECT MAX(fetched_at) FROM us_customer_concentration").fetchone()[0]
    stale = conn.execute("SELECT ? IS NULL OR ? < datetime('now', '-7 days')", (last, last)).fetchone()[0]
    conn.close()
    if stale:
        from pipeline.us_customers import collect as collect_customers

        def work_customers():
            rc = collect_customers()
            print(f"[us_customers] stored={rc['stored']} none={rc['none']} failed={rc['failed']}", flush=True)
            return rc

        run_job("us_customers", work_customers)

    # 시장 기대치 — 칸 구성 회사 애널리스트 컨센서스 일별 스냅샷(§15). 매출 추정 개정은 스냅샷끼리 비교하므로 매일 쌓는다
    from pipeline.vc_expectations import collect as collect_expectations

    def work_expectations():
        re_ = collect_expectations()
        print(f"[vc_expectations] stored={re_['stored']} missing={re_['missing']} status={re_['status']}", flush=True)
        return re_

    run_job("vc_expectations", work_expectations)
    return 1 if isinstance(r, dict) and r.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

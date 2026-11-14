"""국내 종목 도시에 원천 수집 — launchd dev.explorer.krcompany (매일 21:30, pipeline/kr_company_data.py).

  python scripts/collect_kr_company_data.py                    # 종목 마스터 → 공시 → 재무(예산 안에서) → 밸류
  python scripts/collect_kr_company_data.py --only financials  # 한 단계만 (companies|disclosures|financials|valuation|consensus)
  python scripts/collect_kr_company_data.py --budget 1000 --sweep-days 35   # 예산·공시 재확인 창 조정 (밀린 공시 메우기)

단계마다 job_runs(kr_companies·kr_disclosures·kr_financials·kr_valuation)에 ok/partial/error를 남기고,
한 단계가 실패해도 다음 단계는 돈다. 하나라도 error면 종료 코드 1(관리자 health의 launchd 항목이 잡는다).
DART 호출은 네 단계가 한 예산(--budget, 기본 DAILY_BUDGET)을 나눠 쓴다. 밸류는 네이버라 예산과 무관.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db

STEPS = ("companies", "disclosures", "financials", "valuation", "consensus", "preliminary")


def main() -> int:
    from config import DART_API_KEY
    from pipeline import kr_company_data as kr
    from pipeline.ops import run_job
    from services.market_valuation import fetch_market_valuation
    from services.consensus_service import refresh_consensus

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=STEPS)
    ap.add_argument("--budget", type=int, default=kr.DAILY_BUDGET)
    ap.add_argument("--top", type=int, default=kr.TOP_N)
    ap.add_argument("--sweep-days", type=int, default=kr.SWEEP_DAYS)
    args = ap.parse_args()

    init_db()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    client = kr.DartClient(DART_API_KEY, args.budget)
    conn = get_connection()
    failed = []

    def step(key, job, fn):
        if args.only and args.only != key:
            return
        try:
            r = run_job(job, fn)
        except Exception as e:  # noqa: BLE001 — run_job이 error로 기록했다. 다음 단계는 계속
            print(f"[{job}] 실패: {type(e).__name__}")
            failed.append(job)
            return
        print(f"[{job}]", r)
        if isinstance(r, dict) and r.get("status") == "error":
            failed.append(job)

    try:
        step("companies", "kr_companies", lambda: kr.refresh_companies(conn, client))
        tgts = kr.targets(conn, args.top)
        print(f"[targets] {len(tgts)}개사 (보유·관심 {sum(t['tier'] != 'market_cap' for t in tgts)})")
        step("disclosures", "kr_disclosures", lambda: kr.collect_disclosures(conn, client, tgts, today, args.sweep_days))
        step("financials", "kr_financials", lambda: kr.collect_financials(conn, client, tgts, today))
        step("valuation", "kr_valuation", lambda: fetch_market_valuation(conn))
        # 목표가 컨센서스 — 보유·관심 묶음 종목만(시총 상위는 화면 머리에 쓰이지 않는다). 네이버라 DART 예산과 무관
        mine = list(dict.fromkeys(t["stock_code"] for t in tgts if t["tier"] in ("portfolio", "watch")))
        step("consensus", "kr_consensus", lambda: refresh_consensus(mine))
        # 잠정실적 공시 숫자(분기 손익 흐름 1단계) — 최근 ~30건만 돌린다. 이미 처리된 공시는 건너뛴다
        from pipeline.kr_preliminary import collect as collect_preliminary
        step("preliminary", "kr_preliminary", lambda: collect_preliminary(limit=30))
    finally:
        conn.close()
    print(f"[krcompany] DART 호출 {client.calls}/{args.budget}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

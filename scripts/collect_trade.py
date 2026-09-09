"""수출입(무역) 통계 수집 — 관세청 품목별 수출입실적 (docs/specs/trade-follow.md, D-064·D-140).

- 개인 워치리스트 CSV(scripts/trade_watchlist.local.csv, gitignore)가 있으면 trade_follow에 멱등 시드 후 수집.
  없으면 기본 세트(11품목)만.
- 최신 window부터 역순 수집(멱등 upsert). 결과로 ok/partial/error 판정(D-140).
- `--if-fresh`: 원천 최신월을 1콜로 확인해 적재분보다 앞설 때만 수집(신선도 폴링, 매일 launchd).
- 관련 종목이 아직 없는 품목은 LLM 논리로 부트스트랩(캡 3).

사용법:
  python scripts/collect_trade.py                 # 전체 (시작월 .env TRADE_COLLECT_START_YYYYMM, 기본 202101)
  python scripts/collect_trade.py --months 24     # 최근 24개월만
  python scripts/collect_trade.py --if-fresh      # 원천이 전진했을 때만
  python scripts/collect_trade.py 854232 8703     # 특정 HS만
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, get_connection
from pipeline.trade import (collect_followed, collect_status, compute_beneficiaries, latest_available_period,
                            latest_stored_period, seed_default_follows, seed_watchlist, _followed)


def _months_ago(n: int) -> str:
    t = date.today()
    y, m = t.year, t.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hs", nargs="*", help="특정 HS만")
    ap.add_argument("--months", type=int, default=None, help="최근 N개월만 (기본: 시작월부터 전체)")
    ap.add_argument("--if-fresh", action="store_true", help="원천 최신월이 적재분보다 앞설 때만 수집")
    ap.add_argument("--no-bene", action="store_true", help="관련 종목 부트스트랩 생략")
    args = ap.parse_args()

    init_db()
    seeded = seed_watchlist()
    if seeded.get("seeded"):
        print(f"[trade] 워치리스트 CSV 시드 {seeded['seeded']}품목 ({seeded['source']})", flush=True)
    if not _followed():
        print(f"[trade] 팔로우가 비어 기본 세트 {seed_default_follows()}개 시드", flush=True)

    from pipeline.ops import record_run, run_job

    if args.if_fresh:
        probe = (_followed() or [{"hs_code": "8542"}])[0]["hs_code"]
        try:
            upstream = latest_available_period(probe)
        except Exception as e:  # noqa: BLE001
            record_run("collect_trade", "error", f"신선도 확인 실패: {e}"[:200])
            print(f"[trade] 신선도 확인 실패: {e}", flush=True)
            return
        stored = latest_stored_period()
        if upstream and stored and upstream <= stored:
            record_run("collect_trade", "skipped", f"원천 최신 {upstream} = 적재 {stored} — 전진 없음")
            print(f"[trade] 전진 없음 (원천 {upstream} · 적재 {stored})", flush=True)
            return
        print(f"[trade] 원천 {upstream} > 적재 {stored} — 수집 시작", flush=True)
        if args.months is None:
            args.months = 24    # 현행화 수집은 정정 반영 범위(최근 2년)만

    def _work():
        r = collect_followed(only=args.hs or None, strt_yymm=_months_ago(args.months) if args.months else None)
        print(f"[trade] 수집 {r['stored_rows']}행 · 실패 {r['failed']} (품목 {r['items']}, {r.get('range')})", flush=True)
        if not args.no_bene:
            conn = get_connection()
            missing = [row["hs_code"] for row in conn.execute(
                "SELECT hs_code FROM trade_follow WHERE active=1 AND hs_code NOT IN "
                "(SELECT DISTINCT hs_code FROM trade_beneficiaries) ORDER BY hs_code LIMIT 3")]
            conn.close()
            for hs in missing:
                compute_beneficiaries(hs)
            r["beneficiaries_bootstrapped"] = len(missing)
        r["status"] = collect_status(r)
        return r

    run_job("collect_trade", _work)


if __name__ == "__main__":
    main()

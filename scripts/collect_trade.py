"""수출입(무역) 통계 수집 — 관세청 품목별 수출입실적 (docs/specs/trade-follow.md).

팔로우 품목의 월별 수출입 통계를 수집(연 단위 분할)하고, 관련 종목이 아직 없는 품목은
LLM 논리로 부트스트랩(캡 3). 관세청 데이터는 월 갱신이라 월 1회 cron으로 충분.

선행: .env DATA_GO_KR_KEY (공공데이터포털 관세청_품목별 수출입실적 서비스키).

사용법:
  python scripts/collect_trade.py            # 팔로우 전체 (없으면 기본 세트 시드)
  python scripts/collect_trade.py 854232     # 특정 HS만
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, get_connection
from pipeline.trade import collect_followed, compute_beneficiaries, seed_default_follows, _followed


def main():
    init_db()
    only = sys.argv[1:] or None
    if not _followed():
        print(f"[trade] 팔로우가 비어 기본 세트 {seed_default_follows()}개 시드")

    from pipeline.ops import run_job

    def _work():
        r = collect_followed(only=only)
        print(f"[trade] 수집 {r['stored_rows']}행 · 실패 {r['failed']} (품목 {r['items']})")
        # 관련 종목 미지목 품목 부트스트랩 (LLM, 캡 3)
        conn = get_connection()
        missing = [row["hs_code"] for row in conn.execute(
            "SELECT hs_code FROM trade_follow WHERE active=1 AND hs_code NOT IN "
            "(SELECT DISTINCT hs_code FROM trade_beneficiaries) LIMIT 3").fetchall()]
        conn.close()
        for hs in missing:
            compute_beneficiaries(hs)
        print(f"[trade] 관련 종목 부트스트랩 {len(missing)}품목")
        return {**r, "beneficiaries_bootstrapped": len(missing)}
    run_job("collect_trade", _work)   # 관리자 플래그 게이트 + 실행 로그 (D-055)


if __name__ == "__main__":
    main()

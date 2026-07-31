"""어젯밤 미국장 브리핑 사전 생성 — 미국장 마감 후 1회 (D-098).

홈 진입 시 lazy 생성(D-095)이 fallback이지만, 첫 로딩이 sonnet 종합 ~2분을 기다린다.
미국장 마감 후(≈05:00 KST) 크론으로 미리 build_briefing(force=True)해 캐시를 데우면 첫 로딩도 즉답.
signature 캐시라 재료(무버·담론·헤드라인) 안 바뀌면 sonnet 재호출 없음.

30분 수집 체인(run_chain.sh)엔 넣지 않는다 — 장중이면 거래대금이 계속 바뀌어 signature가 매번 달라져
sonnet이 30분마다 재호출(비용 위반). 하루 1회, 마감 뒤가 맞는 케이던스.

권장 crontab (KST, 미국장 마감 05:00 + 수집 여유):
    10 6 * * 2-6  cd <repo> && ./.venv/bin/python scripts/compute_briefing.py >> logs/briefing.log 2>&1

사용법: python scripts/compute_briefing.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db


def main():
    init_db()
    from pipeline.ops import run_job

    def _work():
        from pipeline.us_briefing import build_briefing
        b = build_briefing(force=True)
        top = b["clusters"][0]["label"] if b["clusters"] else "-"
        syn = "종합O" if b["synthesis"] else "종합X(스켈레톤)"
        print(f"[briefing] status={b['status']} trade_date={b['trade_date']} "
              f"상위섹터={top} {syn} movers={len(b['movers'])} idio={len(b['idiosyncratic'])}")
        return {"status": b["status"], "movers": len(b["movers"]), "synthesis": bool(b["synthesis"])}

    run_job("compute_briefing", _work)   # 관리자 플래그 게이트 + 실행 로그 (D-055)


if __name__ == "__main__":
    main()

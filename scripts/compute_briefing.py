"""어젯밤 미국장 브리핑 생성 — build_briefing(force=True) (D-098·D-100).

기본 갱신 수단은 **홈 카드의 '지금 업데이트' 버튼**(같은 경로를 force=True로 호출)이다.
이 스크립트는 그 버튼과 동치인 CLI 진입점 — 크론 자동화를 원할 때만 선택적으로 건다(필수 아님).
일반 홈 로드는 최신 스냅샷을 순수 읽기(재종합 없음, D-100)하므로 갱신은 버튼/이 스크립트로만 일어난다.

선택 crontab (KST, 매일 아침 8시 — 전날 미국장 결산 미리 데우기):
    0 8 * * *  cd <repo> && ./.venv/bin/python scripts/compute_briefing.py >> logs/briefing.log 2>&1

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

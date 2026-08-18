"""어젯밤 미국장 브리핑 생성 — build_briefing(force=True) (D-098·D-100).

기본 갱신 수단은 **홈 카드의 '지금 업데이트' 버튼**(같은 경로를 force=True로 호출)이다.
이 스크립트는 그 버튼과 동치인 CLI 진입점 — 크론 자동화를 원할 때만 선택적으로 건다(필수 아님).
일반 홈 로드는 최신 스냅샷을 순수 읽기(재종합 없음, D-100)하므로 갱신은 버튼/이 스크립트로만 일어난다.

launchd 등록됨(D-112): `dev.explorer.usbriefing` 매일 07:30 KST — 텔레그램 발송(08:00)보다
먼저 돌아야 그날 것이 실린다. 매크로(② 섹션 입력)를 먼저 갱신하고 브리핑을 종합한다.
비용: 매크로 신호등 + 브리핑 종합 각 sonnet 1콜(둘 다 signature 캐시라 재료 불변이면 0콜).

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
        # 매크로(D-101)는 라우터의 lazy 게이트가 `as_of is None`일 때만 걸려, 한 번 채워지면
        # 수동 버튼 외엔 영구히 묵는다(실측 6일). 브리핑 ② 섹션의 입력이라 여기서 먼저 갱신한다.
        # 실패는 흡수 — 매크로가 없어도 브리핑은 나가야 한다 (D-112).
        try:
            from pipeline.macro import snapshot_macro
            snap = snapshot_macro()
            print(f"[briefing] 매크로 갱신 {snap.get('rows')}행 · "
                  f"지표 {len(snap.get('indicators') or [])} · "
                  f"degraded={snap.get('degraded') or '없음'}")
        except Exception as e:  # noqa: BLE001
            print(f"[briefing] 매크로 갱신 실패(무시): {type(e).__name__}: {str(e)[:120]}")

        # 지수(① 섹션 입력)도 자체 스케줄이 없어 묶는다. 모듈이 아직 없거나 이름이 바뀌면
        # 조용히 건너뛴다 — 지수 없으면 ① 섹션만 빠지고 브리핑은 정상 발행된다 (D-112).
        try:
            from pipeline.indices import snapshot_indices
            snap = snapshot_indices()
            print(f"[briefing] 지수 갱신 {snap}")
        except ImportError:
            print("[briefing] 지수 모듈 없음 — ① 섹션 생략")
        except Exception as e:  # noqa: BLE001
            print(f"[briefing] 지수 갱신 실패(무시): {type(e).__name__}: {str(e)[:120]}")

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

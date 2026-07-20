"""주제 내러티브 사전 생성 — theme_surge 상위 테마를 미리 opus 서사로.

30분 체인에서 compute_signals 뒤에 실행 (theme_surge 신호가 있어야 함).
hash 가드로 문서 집합이 바뀐 주제만 실제 재생성 — 대부분 캐시 즉답.

사용법: python scripts/compute_narratives.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.narrative import compute_top_narratives


def main():
    init_db()
    r = compute_top_narratives(limit=5)
    print(f"[narrative] 상위 {len(r['topics'])}개 테마 사전 생성")
    for t, st in r["results"].items():
        print(f"  · {t}: {st}")
    # 메가 내러티브 (D-031) — 멤버 해시 가드로 대부분 캐시 즉답, 군집 구성/멤버 버전 변경 시만 opus
    from pipeline.mega_narrative import compute_mega_narratives
    print("[mega-narrative]", compute_mega_narratives())


if __name__ == "__main__":
    main()

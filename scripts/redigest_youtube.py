"""유튜브 자막 raw 사후 치유 — opus 요약 실패로 raw로 굳은 문서를 재요약.

수집 당시 opus 실패 시 커넥터는 자막 raw를 저장하고, discover()의 seen-skip 때문에
그 영상을 다시 건드리지 않는다 → raw가 영구화된다. 이 배치가 저장분을 직접 스캔해
정리본으로 치유한다. 30분 체인 편승(회차당 소수) + 수동 백필 겸용.

사용법: python scripts/redigest_youtube.py [limit]   # 기본 5, 수동 백필은 크게
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.connectors.youtube import redigest_youtube


def main():
    init_db()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    r = redigest_youtube(limit=limit)
    print(f"[redigest_youtube] 스캔 {r['scanned']} · 정리본 {r['digested']} · 실패 {r['failed']}")


if __name__ == "__main__":
    main()

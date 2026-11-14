"""이번 주 큰 그림 생성 (ia-redesign §4.25, D-313 4) — launchd `bigpicture` 매주 월 07:00(CATCHUP 보충).

  python scripts/weekly_big_picture.py            # 정기(trigger=weekly)
  python scripts/weekly_big_picture.py --event    # 16:00 마감 정리 뒤 조건 실행(새 버전 3편+ · 주 7회 한도 안)
입력 해시가 같으면 LLM 없이 건너뛴다. 결과는 job_runs('weekly_big_picture')에 남는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402


def main() -> int:
    init_db()
    from pipeline.weekly_big_picture import run
    r = run("event" if "--event" in sys.argv[1:] else "weekly")
    print("[big-picture]", r)
    return 1 if r["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())

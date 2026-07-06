"""ETL 척추 수집 실행 스크립트.

사용법:
  python scripts/ingest.py                          # 등록된 모든 소스 (blog+telegram, DB의 활성 목록)
  python scripts/ingest.py --source blog            # 특정 소스만
  python scripts/ingest.py --source blog --target <feed_url>      # 단건 대상 지정
  python scripts/ingest.py --source telegram --target <channel>

주기 실행은 cron/launchd에서 이 스크립트를 호출한다. (예: 30분마다)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.registry import CONNECTORS
from pipeline.runner import run_source


def main():
    parser = argparse.ArgumentParser(description="ETL 척추 수집 실행")
    parser.add_argument("--source", choices=[*CONNECTORS, "all"], default="all")
    parser.add_argument("--target", help="단건 대상 (blog: feed url / telegram: channel명)")
    args = parser.parse_args()

    if args.target and args.source == "all":
        parser.error("--target 사용 시 --source를 지정해야 합니다")

    init_db()
    sources = list(CONNECTORS) if args.source == "all" else [args.source]

    total = {"refs": 0, "docs": 0, "new": 0, "updated": 0, "unchanged": 0}
    for name in sources:
        cls = CONNECTORS[name]
        connector = cls([args.target]) if args.target else cls()
        try:
            stats = run_source(connector)
        except Exception as e:
            print(f"[{name}] 실패: {e}")
            continue
        print(f"[{name}] {stats}")
        for k in total:
            total[k] += stats[k]

    print(f"[total] {total}")


if __name__ == "__main__":
    main()

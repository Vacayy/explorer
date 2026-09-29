"""미국 주요 매체·Fed RSS 헤드라인 수집 (D-206) — 30분 체인 편승, LLM 0.

RSS는 피드당 최근 20~30건만 남아, 브리핑 직전 한 번만 받으면 주말을 낀 시간창(금 마감~월 아침)을
채우지 못한다. 그래서 체인마다 조금씩 쌓는다. 실패 피드는 출력으로 남긴다.

사용법: python scripts/fetch_macro_news.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db


def main():
    init_db()
    from pipeline.macro_news import fetch_feeds
    r = fetch_feeds()
    failed = ", ".join(f"{f['key']}({f['reason']})" for f in r["failed"]) or "없음"
    print(f"[macro_news] 성공 {len(r['ok'])}개 · 실패 {failed}", flush=True)


if __name__ == "__main__":
    main()

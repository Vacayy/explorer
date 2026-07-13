"""블로그 요약본 → 원문 소급 백필 (1회성).

RSS가 요약만 준 블로그 문서(markdown < 600자)의 원문 페이지를 스크랩해
전문으로 교체한다. store_document 재사용 — 마크다운 변환·해시·UPDATE 자동,
content_hash가 바뀌므로 이후 수집 사이클에서 재enrich 대상이 된다.

사용법: python scripts/backfill_blog_content.py [--limit N]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.base import RawDoc
from pipeline.store import store_document
from services.blog_service import fetch_full_content


def main(limit: int):
    init_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, source_id, title, url, published_at, length(markdown) L
        FROM raw_documents
        WHERE source_type='blog' AND url != '' AND length(markdown) < 600
        ORDER BY published_at DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    print(f"[backfill] 대상 {len(rows)}건 (600자 미만)")

    stats = {"updated": 0, "unchanged": 0, "no_content": 0, "failed": 0}
    for i, r in enumerate(rows, 1):
        try:
            full = fetch_full_content(r["url"])
        except Exception:
            stats["failed"] += 1
            continue
        if not full or len(full) < 300:
            stats["no_content"] += 1
            continue
        res = store_document(RawDoc(
            source_type="blog", source_id=r["source_id"], title=r["title"],
            url=r["url"], published_at=r["published_at"] or "",
            raw_content=full, kind="html"))
        new_len = res.get("status")
        if new_len == "updated":
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
        if i % 25 == 0:
            print(f"  … {i}/{len(rows)} — {stats}")
        time.sleep(0.4)  # 원문 서버 배려
    print("[backfill] 완료:", stats)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    main(args.limit)

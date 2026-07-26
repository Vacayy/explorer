"""네이버 블로그 본문 잘림 복구 (일회성) — RSS excerpt만 저장된 문서를 원문 재수집.

배경: 블로그 커넥터가 RSS 본문 600자 이상이면 원문 스크랩을 건너뛰었는데, 네이버 RSS는
길이와 무관하게 늘 요약만 준다(본문은 iframe). 커넥터는 수정됨(항상 스크랩). 이 스크립트는
이미 잘린 채 저장된 과거 문서를 원문으로 재수집한다 — store_document이 재정규화·재태깅까지 처리.

사용법: python scripts/repair_naver_bodies.py [--max-len 3000] [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.base import RawDoc
from pipeline.store import store_document
from services.blog_service import fetch_full_content


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    max_len = 3000
    if "--max-len" in args:
        max_len = int(args[args.index("--max-len") + 1])
    init_db()
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, source_id, title, url, published_at, length(raw_content) AS rc "
        "FROM raw_documents WHERE source_type='blog' AND url LIKE '%blog.naver.com%' "
        "AND length(raw_content) < ? ORDER BY id DESC", (max_len,)).fetchall()
    conn.close()
    print(f"[repair] 후보 {len(rows)}건 (raw_content < {max_len}자)")

    repaired = skipped = failed = 0
    for r in rows:
        try:
            full = fetch_full_content(r["url"])
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ doc {r['id']} fetch 실패: {e}")
            failed += 1
            continue
        if not full or len(full) <= r["rc"]:
            skipped += 1
            continue
        print(f"  {'(dry)' if dry else '→'} doc {r['id']} {r['rc']}자 → {len(full)}자 · {(r['title'] or '')[:40]}")
        if dry:
            repaired += 1
            continue
        res = store_document(RawDoc(
            source_type="blog", source_id=r["source_id"], title=r["title"] or "",
            url=r["url"] or "", published_at=r["published_at"] or "",
            raw_content=full, kind="html"))
        if res["status"] in ("updated", "new"):
            repaired += 1
        else:
            skipped += 1
    print(f"[repair] 복구 {repaired} · 스킵(이미 충분/실패한 fetch) {skipped} · fetch실패 {failed}")


if __name__ == "__main__":
    main()

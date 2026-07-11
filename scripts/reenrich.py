"""문서 재태깅 백필 — 어휘 확장(live vocab) 등 태깅 로직 변경 후 소급 적용.

사용법:
  python scripts/reenrich.py --like 'surfslow/%'          # 특정 소스
  python scripts/reenrich.py --days 1                     # 최근 N일 수집분
  python scripts/reenrich.py --like 'a/%' --like 'b/%'    # 복수 프리픽스
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.store import reenrich_document


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--like", action="append", default=[], help="source_id LIKE 패턴")
    ap.add_argument("--days", type=int, help="최근 N일 fetched 문서")
    args = ap.parse_args()
    if not args.like and not args.days:
        ap.error("--like 또는 --days 필요")

    init_db()
    conn = get_connection()
    where, params = [], []
    if args.like:
        where.append("(" + " OR ".join("source_id LIKE ?" for _ in args.like) + ")")
        params += args.like
    if args.days:
        where.append("fetched_at >= datetime('now', ?)")
        params.append(f"-{args.days} days")
    ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM raw_documents WHERE {' AND '.join(where)} ORDER BY id", params)]
    conn.close()

    print(f"[reenrich] {len(ids)}건 시작")
    t = time.time()
    ok = fail = 0
    for i, doc_id in enumerate(ids, 1):
        try:
            m = reenrich_document(doc_id)
            ok += 1 if m else 0
        except Exception as e:
            fail += 1
            print(f"  doc {doc_id} 실패: {str(e)[:80]}")
        if i % 10 == 0:
            print(f"  {i}/{len(ids)} ({time.time()-t:.0f}s)")
    print(f"[reenrich] 완료: {ok} 성공 / {fail} 실패 ({time.time()-t:.0f}s)")


if __name__ == "__main__":
    main()

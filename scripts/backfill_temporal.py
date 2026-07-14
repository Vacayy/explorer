"""기존 문서 시간 방향 백필 (D-021) — enrichments.time_orientation NULL인 것만.

전체 재태깅 없이 title+요약으로 값싼 haiku 분류. 멱등 (이미 채워진 건 skip).
사용법: python scripts/backfill_temporal.py [--limit N]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import classify_temporal


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    init_db()
    conn = get_connection()
    q = """SELECT e.doc_id, rd.title, e.summary
           FROM enrichments e JOIN raw_documents rd ON rd.id = e.doc_id
           WHERE e.time_orientation IS NULL AND rd.markdown IS NOT NULL
           ORDER BY rd.published_at DESC"""
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()
    conn.close()
    print(f"백필 대상: {len(rows)}건")

    counts = {}
    for i, r in enumerate(rows, 1):
        t = classify_temporal(r["title"] or "", r["summary"] or "")
        orient = t["time_orientation"]
        if orient:
            conn = get_connection()
            conn.execute(
                "UPDATE enrichments SET time_orientation=?, reference_period=? WHERE doc_id=?",
                (orient, t["reference_period"], r["doc_id"]))
            conn.commit()
            conn.close()
            counts[orient] = counts.get(orient, 0) + 1
        if i % 20 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)} — {counts}")
    print(f"완료: {counts}")


if __name__ == "__main__":
    main()

"""1회성 이관 — source_digests(kind='narrative') → narratives version=1 (D-023).

기존 내러티브(md 덩어리)를 1급 객체로 옮긴다. 인과 엣지는 구버전이라 없음 —
다음 재생성(문서 집합 변경) 시 채워진다. 멱등(이미 있으면 skip).

사용법: python scripts/migrate_narratives.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, get_connection


def main():
    init_db()
    conn = get_connection()
    rows = conn.execute(
        "SELECT key, digest, doc_count, doc_ids_hash, model, created_at "
        "FROM source_digests WHERE kind='narrative'").fetchall()
    migrated = skipped = 0
    for r in rows:
        if conn.execute("SELECT 1 FROM narratives WHERE topic=?", (r["key"],)).fetchone():
            skipped += 1
            continue
        try:
            d = json.loads(r["digest"])
        except Exception:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO narratives (topic, version, title, body, doc_count, doc_ids_hash, model, created_at) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?)",
            (r["key"], d.get("title"), d.get("narrative"), r["doc_count"], r["doc_ids_hash"],
             r["model"], r["created_at"]))
        migrated += 1
    conn.commit()
    conn.close()
    print(f"[migrate_narratives] 이관 {migrated} · skip {skipped} (전체 {len(rows)})")


if __name__ == "__main__":
    main()

"""기존 텔레그램 문서를 연속 타이핑 묶음으로 병합 (1회성 마이그레이션).

커넥터의 group_bursts와 동일한 규칙(GAP·MAX_GROUP)을 저장된 문서에 소급 적용:
- 그룹 head 문서에 멤버들의 markdown을 이어붙이고 content_hash 재계산
  (커넥터가 앞으로 만들 내용과 동일 → 다음 수집에서 no-op 멱등)
- 멤버 문서 삭제 (entity_links·enrichments FK CASCADE, doc_fts 트리거)
- head 재enrich + 검색 인덱스 재구축

사용법: python scripts/regroup_telegram.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.connectors.telegram import GROUP_GAP_SEC, MAX_GROUP, _parse_dt
from pipeline.store import _hash, reenrich_document


def _groups_for_channel(rows):
    """저장된 문서 행들 → 병합 그룹 (커넥터 group_bursts와 동일 규칙)."""
    groups = []
    for r in rows:
        dt = _parse_dt(r["published_at"] or "")
        if groups and len(groups[-1]) < MAX_GROUP:
            prev = _parse_dt(groups[-1][-1]["published_at"] or "")
            if dt and prev and 0 <= (dt - prev).total_seconds() <= GROUP_GAP_SEC:
                groups[-1].append(r)
                continue
        groups.append([r])
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    init_db()
    conn = get_connection()
    channels = [r["c"] for r in conn.execute("""
        SELECT DISTINCT substr(source_id, 1, instr(source_id,'/')-1) c
        FROM raw_documents WHERE source_type='telegram' AND instr(source_id,'/') > 0""")]

    merged_groups = deleted = 0
    heads_to_reenrich = []
    for ch in channels:
        rows = conn.execute("""
            SELECT id, source_id, published_at, markdown, media_json,
                   cast(substr(source_id, instr(source_id,'/')+1) as integer) mid
            FROM raw_documents WHERE source_type='telegram' AND source_id LIKE ? || '/%'
            ORDER BY mid""", (ch,)).fetchall()
        for g in _groups_for_channel(rows):
            if len(g) < 2:
                continue
            head, members = g[0], g[1:]
            merged_md = "\n\n".join((r["markdown"] or "").strip() for r in g if (r["markdown"] or "").strip())
            media = []
            for r in g:
                media += json.loads(r["media_json"]) if r["media_json"] else []
            title = merged_md.split("\n", 1)[0][:80] if merged_md else None
            merged_groups += 1
            deleted += len(members)
            print(f"  [{ch}] #{head['mid']} ← {len(g)}개 병합 ({(title or '')[:40]})")
            if args.dry_run:
                continue
            conn.execute("""
                UPDATE raw_documents SET markdown=?, raw_content=?, content_hash=?,
                    title=COALESCE(?, title), media_json=? WHERE id=?
            """, (merged_md, merged_md, _hash(merged_md), title,
                  json.dumps(media) if media else None, head["id"]))
            member_ids = [r["id"] for r in members]
            ph = ",".join("?" for _ in member_ids)
            conn.execute(f"DELETE FROM raw_documents WHERE id IN ({ph})", member_ids)
            heads_to_reenrich.append(head["id"])
    conn.commit()
    conn.close()
    print(f"\n병합 그룹 {merged_groups}개 · 흡수된 문서 {deleted}건" + (" (dry-run)" if args.dry_run else ""))
    if args.dry_run:
        return

    print("head 재태깅…")
    for i, doc_id in enumerate(heads_to_reenrich, 1):
        try:
            reenrich_document(doc_id)
        except Exception as e:
            print(f"  doc {doc_id} 실패: {str(e)[:60]}")
        if i % 10 == 0:
            print(f"  {i}/{len(heads_to_reenrich)}")

    print("검색 인덱스 재구축…")
    from pipeline.search import build_index, _vec_conn
    # 삭제된 문서의 벡터 제거 후 리빌드
    vconn = _vec_conn()
    if vconn is not None:
        vconn.execute("DELETE FROM doc_vec WHERE rowid NOT IN (SELECT id FROM raw_documents)")
        # 병합 head는 내용이 바뀌었으므로 재임베딩 대상으로
        ph = ",".join("?" for _ in heads_to_reenrich) or "0"
        vconn.execute(f"DELETE FROM doc_vec WHERE rowid IN ({ph})", heads_to_reenrich)
        vconn.commit()
        vconn.close()
    print(build_index())


if __name__ == "__main__":
    main()

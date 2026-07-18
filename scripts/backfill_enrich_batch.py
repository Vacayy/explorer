"""keyword 폴백 문서 배치 재태깅 — 문서 10건/콜 sonnet (D-028 레버 1).

기존 backfill_enrich.py(문서당 1콜, 콜드스타트 병목)의 배치 버전.
1,524건 ≈ 153콜. 배치 실패 시 해당 배치는 keyword로 남아 다음 실행에서 재시도(멱등).

사용법: python scripts/backfill_enrich_batch.py [--limit N] [--batch-size K]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import enrich_batch, llm_engine
from pipeline.store import apply_enrichment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처리할 문서 수 상한 (0=전부)")
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    init_db()
    if llm_engine() != "claude-code":
        print("claude-code 엔진 필요 — .env ENRICH_ENGINE=claude-code")
        sys.exit(1)

    conn = get_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT rd.id, rd.title, rd.markdown, rd.content_hash
        FROM raw_documents rd
        LEFT JOIN enrichments en ON en.doc_id = rd.id
        WHERE en.model = 'keyword' OR en.id IS NULL
        ORDER BY rd.published_at DESC
    """).fetchall()]
    conn.close()
    if args.limit:
        rows = rows[:args.limit]
    print(f"대상: {len(rows)}건 (배치 {args.batch_size}건/콜)")

    ok = failed_batches = 0
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        try:
            results = enrich_batch(
                [{"id": d["id"], "title": d["title"] or "", "markdown": d["markdown"] or ""}
                 for d in batch])
        except Exception as e:
            failed_batches += 1
            print(f"  배치 {i // args.batch_size + 1} 실패 (다음 실행에서 재시도): {str(e)[:120]}")
            continue
        # 배치 단위로 짧게 연결 열고 적용 — cron ingest와의 쓰기 락 경합 최소화
        conn = get_connection()
        for d in batch:
            result = results.get(d["id"])
            if not result:
                continue  # 모델이 해당 번호를 누락 — keyword로 남아 재시도됨
            apply_enrichment(conn, d["id"], d["title"] or "", d["markdown"] or "",
                             d["content_hash"] or "", result)
            ok += 1
        conn.close()
        done = min(i + args.batch_size, len(rows))
        print(f"  진행 {done}/{len(rows)} (적용 {ok}, 실패 배치 {failed_batches})", flush=True)

    print(f"완료: 적용 {ok}건 / 대상 {len(rows)}건 / 실패 배치 {failed_batches}개")


if __name__ == "__main__":
    main()

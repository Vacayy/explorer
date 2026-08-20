"""keyword 폴백 문서 배치 재태깅 — 문서 10건/콜 sonnet (D-028 레버 1 · D-117).

배경: 2026-07-17~08-18 LLM이 죽어 있던 한 달간(D-106) 7,871건이 키워드 폴백으로 태깅됐다.
전체 문서의 69%다. 이 배치가 그 백로그를 소진한다. 배치 실패 시 해당 배치는 keyword로 남아
다음 실행에서 재시도(멱등).

**순서**: 최신순(published_at DESC) — 단순하게 밀린 것부터 순서대로 소진한다.
(우선순위 가중은 시도했다가 폐기: 사용자 지시 "우선순위 생각하지 말고 그냥 필요한 순서대로".)

**예산(D-117)**: `--budget-calls`로 LLM 호출 수를 직접 제한한다. 문서 수 상한(`--limit`)보다
비용에 직결되고, 세션 소진 속도를 통제할 수 있다.

사용법:
  python scripts/backfill_enrich_batch.py --budget-calls 20        # 20콜(≈200건)만
  python scripts/backfill_enrich_batch.py --dry-run                # 남은 물량만 출력
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import enrich_batch, llm_engine
from pipeline.store import apply_enrichment

_ROWS_SQL = """
SELECT rd.id, rd.title, rd.markdown, rd.content_hash
FROM raw_documents rd
LEFT JOIN enrichments en ON en.doc_id = rd.id
WHERE en.model = 'keyword' OR en.id IS NULL
ORDER BY rd.published_at DESC
"""


def _fetch() -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(_ROWS_SQL)]
    finally:
        conn.close()


def run(batch_size: int, budget_calls: int, dry_run: bool) -> dict:
    rows = _fetch()
    print(f"남은 대상 {len(rows)}건")
    planned = min(budget_calls, -(-len(rows) // batch_size)) if budget_calls else -(-len(rows) // batch_size)
    print(f"배치 {batch_size}건/콜 · 예산 {budget_calls or '무제한'}콜 → 이번 실행 최대 {planned}콜 "
          f"({min(planned * batch_size, len(rows))}건)")
    if dry_run:
        return {"dry_run": True, "candidates": len(rows), "planned_calls": planned}

    ok = failed = calls = 0
    for i in range(0, len(rows), batch_size):
        if budget_calls and calls >= budget_calls:
            print(f"  예산 {budget_calls}콜 소진 — 남은 {len(rows) - i}건은 다음 실행에서")
            break
        batch = rows[i:i + batch_size]
        calls += 1
        try:
            results = enrich_batch(
                [{"id": d["id"], "title": d["title"] or "", "markdown": d["markdown"] or ""}
                 for d in batch])
        except Exception as e:  # noqa: BLE001 — 배치 실패는 keyword로 남아 재시도된다
            failed += 1
            print(f"  콜 {calls} 실패(재시도 대상): {str(e)[:120]}", flush=True)
            continue
        # 배치 단위로 짧게 연결 열고 적용 — cron ingest와의 쓰기 락 경합 최소화
        conn = get_connection()
        try:
            for d in batch:
                result = results.get(d["id"])
                if not result:
                    continue      # 모델이 해당 번호를 누락 — keyword로 남아 재시도됨
                apply_enrichment(conn, d["id"], d["title"] or "", d["markdown"] or "",
                                 d["content_hash"] or "", result)
                ok += 1
        finally:
            conn.close()
        print(f"  콜 {calls}/{planned} · 적용 누계 {ok}건", flush=True)

    return {"applied": ok, "calls": calls, "failed_calls": failed, "candidates": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--budget-calls", type=int, default=0, help="이번 실행 LLM 호출 상한 (0=무제한)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    init_db()
    if llm_engine() != "claude-code":
        print("claude-code 엔진 필요 — .env ENRICH_ENGINE=claude-code")
        sys.exit(1)

    from pipeline.ops import run_job
    r = run_job("backfill_enrich", lambda: run(
        args.batch_size, args.budget_calls, args.dry_run))
    print("[backfill_enrich]", r)


if __name__ == "__main__":
    main()

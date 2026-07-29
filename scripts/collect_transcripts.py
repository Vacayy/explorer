"""미국 기업 실적 컨콜 transcript 수집 (docs/specs/transcript-follow.md).

팔로우한 미국 기업의 신규 컨콜을 FMP에서 받아 raw_documents(source_type='transcript')로 적재.
이후 enrich·doc_causal·digests는 기존 파이프라인이 인수 — 온톨로지 편입은 doc_causal cron에서.

선행: .env에 FMP_API_KEY (무료 발급: financialmodelingprep.com).

라운드로빈: 모든 기업의 최신 분기 먼저 → 그 다음 이전 분기. AV 무료 한도(25/day)라
요청 예산 안에서만 수집하고, 매일 재실행하면 이미 저장된 분기는 스킵하며 backlog가 이어짐.

사용법:
  python scripts/collect_transcripts.py            # 라운드로빈 (없으면 기본 세트 시드), 예산 22
  python scripts/collect_transcripts.py --budget 10
  python scripts/collect_transcripts.py NVDA AAPL  # 특정 티커만
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.transcript import (collect_roundrobin, digest_pending, extract_proxies,
                                 seed_default_follows, seed_proxies, backfill_call_dates, _followed)


def main():
    init_db()
    args = sys.argv[1:]
    budget = 22
    dry_run = False
    if "--dry-run" in args:
        dry_run = True
        args.remove("--dry-run")
    if "--budget" in args:
        i = args.index("--budget")
        budget = int(args[i + 1])
        del args[i:i + 2]
    only = [a.upper() for a in args] or None

    if not _followed():
        n = seed_default_follows()
        print(f"[transcript] 팔로우가 비어 기본 세트 {n}개 시드")

    if dry_run:   # 예산·sleep 없이 '무엇을 요청할지'만 (D-081)
        r = collect_roundrobin(only=only, dry_run=True)
        print(f"[transcript][dry-run] 요청 예정 {r['would_request']}건 · 캐시 스킵 {r['skipped_cache']}")
        for p in r["planned"][:budget]:
            print(f"  → {p}")
        if r["would_request"] > budget:
            print(f"  … 외 {r['would_request'] - budget}건 (예산 {budget} 초과분은 다음 회차)")
        return

    from pipeline.ops import run_job

    def _work():
        r = collect_roundrobin(request_budget=budget, only=only)
        print(f"[transcript] 요청 {r['requests']}/{r['budget']} · 신규 {r['stored']}건 적재 · "
              f"빈응답 {r['empty']} · 캐시 스킵 {r['skipped_cache']} · 예산소진={r['exhausted']}")
        if r["stored"]:
            bc = backfill_call_dates(only=only)  # 신규분 call_date를 실제 발표일로 (yfinance, D-084)
            print(f"[transcript] 발표일 교정 {bc['updated']}건")
        n = digest_pending(limit=max(r["stored"], 5))  # 신규분 핵심 정리 생성(sonnet)
        print(f"[transcript] 핵심 정리 {n}건 생성")
        seed_proxies()
        px = extract_proxies()  # 관찰 프록시 자동 트래킹 (haiku, 멱등, D-048)
        print(f"[transcript] 프록시 추출 {px.get('extracted', 0)}건")
        return {**r, "digested": n, "proxies": px.get("extracted", 0)}
    run_job("collect_transcripts", _work)   # 관리자 플래그 게이트 + 실행 로그 (D-055)


if __name__ == "__main__":
    main()

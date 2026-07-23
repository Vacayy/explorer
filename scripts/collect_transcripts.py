"""미국 기업 실적 컨콜 transcript 수집 (docs/specs/transcript-follow.md).

팔로우한 미국 기업의 신규 컨콜을 FMP에서 받아 raw_documents(source_type='transcript')로 적재.
이후 enrich·doc_causal·digests는 기존 파이프라인이 인수 — 온톨로지 편입은 doc_causal cron에서.

선행: .env에 FMP_API_KEY (무료 발급: financialmodelingprep.com).

사용법:
  python scripts/collect_transcripts.py            # 팔로우 전체 (없으면 기본 세트 시드)
  python scripts/collect_transcripts.py NVDA AAPL  # 특정 티커만 (적재 검증용)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.transcript import collect_followed, digest_pending, seed_default_follows, _followed


def main():
    init_db()
    only = [a.upper() for a in sys.argv[1:]] or None

    if not _followed():
        n = seed_default_follows()
        print(f"[transcript] 팔로우가 비어 기본 세트 {n}개 시드")

    from pipeline.ops import run_job

    def _work():
        r = collect_followed(only=only)
        print(f"[transcript] 신규 {r['stored']}건 적재 · 스킵 {r['skipped']} · 실패 {r['failed']} "
              f"(대상 {r['tickers']}개 기업)")
        n = digest_pending(limit=max(r["stored"], 5))  # 신규분 핵심 정리 생성
        print(f"[transcript] 핵심 정리 {n}건 생성")
        return {**r, "digested": n}
    run_job("collect_transcripts", _work)   # 관리자 플래그 게이트 + 실행 로그 (D-055)


if __name__ == "__main__":
    main()

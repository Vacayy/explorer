"""검색 인덱스 빌드 — FTS 리빌드 + 신규 문서 임베딩 + 청크 인덱스(D-132) (cron 체인에서 주기 실행)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.chunks import build_chunk_index
from pipeline.search import build_index

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks-only", action="store_true")
    ap.add_argument("--limit-docs", type=int, default=None, help="청크 빌드 문서 수 상한(첫 백필 분할용)")
    args = ap.parse_args()
    init_db()
    if not args.chunks_only:
        print("[search-index]", build_index(), flush=True)
    print("[chunk-index]", build_chunk_index(limit_docs=args.limit_docs), flush=True)

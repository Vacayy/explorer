"""검색 인덱스 빌드 — FTS 리빌드 + 신규 문서 임베딩 (cron 체인에서 주기 실행)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.search import build_index

if __name__ == "__main__":
    init_db()
    print("[search-index]", build_index())

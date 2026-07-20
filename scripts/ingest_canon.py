"""정전(canon) 노트 흡수 + 역사 인과 추출 (D-030).

vault/canon/*.md → source_type='canon' 적재 → opus 역사 인과 추출(멱등).
사용법: python scripts/ingest_canon.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.canon import extract_canon_causal, ingest_canon

if __name__ == "__main__":
    init_db()
    print("[canon-ingest]", ingest_canon())
    print("[canon-causal]", extract_canon_causal())

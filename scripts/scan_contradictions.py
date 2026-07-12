"""모순 감지 배치 (일 1회) — 새 문서 × active 지식 대조 (K2).

사용법: python scripts/scan_contradictions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.contradiction import scan_contradictions

if __name__ == "__main__":
    init_db()
    print("[contradiction]", scan_contradictions())

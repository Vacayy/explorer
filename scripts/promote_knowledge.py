"""지식 승격 배치 (주 1회) — 공고화: 반복·독립 관측 주장 → 승인 큐.

사용법: python scripts/promote_knowledge.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.consolidation import promote_batch, promote_causal_edges

if __name__ == "__main__":
    init_db()
    print("[promote]", promote_batch())
    print("[promote-causal]", promote_causal_edges())

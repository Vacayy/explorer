"""LLM 엔진 생사 프로브 (30분 체인 편승, D-106).

정상이면 하루 1콜, 고장 중이면 매 회차 재시도(복구 즉시 감지).
결과는 job_runs('llm_probe')에 남아 관리자 페이지·홈 브리핑 경고의 근거가 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.ops import probe_llm

if __name__ == "__main__":
    init_db()
    print("[llm-probe]", probe_llm())

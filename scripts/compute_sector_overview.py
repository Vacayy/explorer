"""산업 개괄(AI) 생성 (ia-redesign §4.35, D-327-3, backend/pipeline/sector_overview.py).

섹터에 걸린 내러티브가 바뀐 섹터만, 섹터당 주 1회 상한으로 sonnet 1콜. 관리자 플래그 `sector_overview`가 켜져 있을 때만 돈다(기본 off).
launchd `sectoroverview` — 매일 06:20(주간 내러티브 06:00 뒤). 플래그가 꺼져 있으면 모델 호출 없이 끝난다.

  python scripts/compute_sector_overview.py                 # 필요한 섹터 전부
  python scripts/compute_sector_overview.py 반도체·전자부품     # 한 섹터만
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.ops import flag_enabled, record_run, run_job
from pipeline.sector_overview import JOB, run


def main():
    init_db()
    r = run(sys.argv[1:] or None)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] sector_overview — 생성 {len(r['made'])} · 건너뜀 {len(r['skipped'])} · 실패 {r['failed']}")
    return r


if __name__ == "__main__":
    if not flag_enabled(JOB, default=False):      # 기본 off — 관리자가 켜야 돈다
        record_run(JOB, "skipped", "비활성(기본 off)")
        print(f"[{JOB}] skipped — flag off (default)")
    else:
        run_job(JOB, main)

"""포트폴리오 텔레그램 알림 (D-214, launchd dev.explorer.pfintraday / pfclose).

  python scripts/portfolio_alerts.py --intraday           # 장중 급등락 + 신규 공시 (평일 09:00–18:00 30분)
  python scripts/portfolio_alerts.py --close              # 계좌 요약 + 기술적 신호 + 공시 (평일 16:50)
  python scripts/portfolio_alerts.py --close --dry-run    # 보내지 않고 미리보기 (보낸 것으로 기록하지 않음)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.ops import record_run
from pipeline.portfolio_alerts import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--intraday", action="store_true")
    mode.add_argument("--close", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    init_db()
    name = "intraday" if args.intraday else "close"
    started = time.time()
    try:
        result = run(name, dry_run=args.dry_run)
        print("[portfolio-alerts]", result)
        if not args.dry_run:
            record_run(f"pf_{name}", "error" if result.get("errors") else "ok", str(result), int((time.time() - started) * 1000))
    except Exception as e:  # 실패는 job_runs에 남기고 종료코드로 드러낸다
        if not args.dry_run:
            record_run(f"pf_{name}", "error", f"{type(e).__name__}: {str(e)[:200]}", int((time.time() - started) * 1000))
        raise

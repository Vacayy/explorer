"""관측 정기 작업 (docs/specs/observability.md, D-283).

  python scripts/observe.py --weekly            # 주간 텔레그램 리포트(월 07:05)
  python scripts/observe.py --weekly --dry-run  # 보내지 않고 출력만
  python scripts/observe.py --alerts            # 즉시 경고(1시간마다) — 상태가 바뀔 때만 보낸다
결과는 job_runs('observe_weekly' / 'observe_alerts')에 남는다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import record_run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--alerts", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    init_db()
    from pipeline import observe
    started = time.time()
    if a.weekly:
        text = observe.weekly_message()
        if a.dry_run:
            print(text)
            return 0
        from pipeline.notify import send_telegram
        ok = send_telegram(text)
        record_run("observe_weekly", "ok" if ok else "error", f"sent={ok} chars={len(text)}", int((time.time() - started) * 1000))
        return 0 if ok else 1
    if a.alerts:
        r = observe.check_alerts(dry_run=a.dry_run)
        print(r)
        if not a.dry_run:
            record_run("observe_alerts", "ok", str(r)[:500], int((time.time() - started) * 1000))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""미국 수요 기업 분기 실적 수집 (docs/specs/value-chain.md §6) — SEC XBRL companyfacts, LLM 0.

  python scripts/collect_us_fundamentals.py   # launchd usfund 매일 08:10 (실적 발표 뒤 10-Q가 올라오면 반영)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402,F401 — .env(SEC_USER_AGENT)
from database import init_db  # noqa: E402
from pipeline.ops import run_job  # noqa: E402


def main() -> int:
    init_db()
    from pipeline.us_fundamentals import collect

    def work():
        r = collect()
        print(f"[us_fundamentals] {r}", flush=True)
        return r

    r = run_job("us_fundamentals", work)
    return 1 if isinstance(r, dict) and r.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

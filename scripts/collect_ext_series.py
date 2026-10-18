"""외부 월간 시계열 수집 (docs/specs/value-chain.md §7) — WSTS·Census 데이터센터·SEAJ·대만 수출수주, LLM 0.

  python scripts/collect_ext_series.py   # launchd extseries 매일 10:30 (발표일이 제각각이라 매일 확인·덮어쓰기)
한 원천 실패는 나머지를 막지 않고, 결과는 job_runs('ext_series')에 ok/partial/error로 남는다.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db  # noqa: E402
from pipeline.ops import run_job  # noqa: E402

SOURCES = ["ext_wsts", "ext_census_dc", "ext_seaj", "ext_tw_orders"]


def main() -> int:
    init_db()

    def work():
        results, failed = {}, []
        for name in SOURCES:
            try:
                r = importlib.import_module(f"pipeline.{name}").collect()
            except Exception as e:  # noqa: BLE001 — 한 원천 실패는 기록하고 다음으로
                r = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:150]}"}
            results[name] = {k: r.get(k) for k in ("status", "stored", "latest", "error") if r.get(k) is not None}
            if r.get("status") != "ok":
                failed.append(name)
            print(f"[ext_series] {name}: {results[name]}", flush=True)
        status = "error" if len(failed) == len(SOURCES) else "partial" if failed else "ok"
        return {"status": status, "failed": failed, "sources": len(SOURCES)}

    r = run_job("ext_series", work)
    return 1 if isinstance(r, dict) and r.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

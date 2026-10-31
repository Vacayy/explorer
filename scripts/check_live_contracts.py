"""실제 응답 계약 검사 정기 실행 — frontend/scripts/check-live-contracts.mjs를 돌려 job_runs('live_contracts')에 남긴다.

화면을 아무도 열지 않아도 계약 위반(실제 데이터의 null·새 enum·빠진 필드)과 응답 모델 오류(500)를 미리 잡는다
(docs/specs/frontend-api-reliability.md §실제 응답 검사). 실패 항목은 스크립트가 /api/spine/client-errors에 남겨
운영 점검 '화면 API 오류'에 오른다. 백엔드가 떠 있지 않으면 skipped로 남긴다(조용히 넘어가지 않음).

  python scripts/check_live_contracts.py
"""
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))
from pipeline.ops import record_run  # noqa: E402

BASE = "http://localhost:8000"


def main() -> int:
    started = time.time()
    try:
        urllib.request.urlopen(f"{BASE}/api/spine/admin/health", timeout=10)
    except Exception as e:  # noqa: BLE001
        record_run("live_contracts", "skipped", f"백엔드 응답 없음: {type(e).__name__}", 0)
        print("백엔드가 떠 있지 않아 건너뜀")
        return 0
    node = shutil.which("node")
    if not node:
        record_run("live_contracts", "error", "node를 PATH에서 찾지 못함", 0)
        return 1
    p = subprocess.run([node, "scripts/check-live-contracts.mjs"], cwd=PROJECT / "frontend",
                       capture_output=True, text=True, timeout=1800)
    out = (p.stdout or "") + (p.stderr or "")
    summary = next((ln for ln in out.splitlines() if ln.startswith("실제 응답 계약 검사")), out[-300:])
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    record_run("live_contracts", "ok" if p.returncode == 0 else "error",
               (summary + (" · " + " | ".join(fails[:3]) if fails else ""))[:500], int((time.time() - started) * 1000))
    print(out)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())

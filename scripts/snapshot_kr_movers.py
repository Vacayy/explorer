"""전일 국장 거래대금 상위 일별 스냅샷 (launchd: 평일 16:20 KST, D-108).

일별로 쌓아야 '신규 진입'(직전 스냅샷 대비) 판정이 가능하다. 멱등 — 같은 날 재실행하면 갱신.
LLM 0콜. FDR 1콜이라 수 초.

FDR(KRX 목록)이 일시 오류(HTTPError)를 내면 그날 스냅샷이 통째로 빠진다(실측 2026-09-08) —
2분 간격 3회 재시도하고, 결과를 job_runs('snapshot_kr_movers')에 남긴다(전엔 로그 파일에만).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.kr_movers import get_leaders
from pipeline.ops import record_run

if __name__ == "__main__":
    init_db()
    t0 = time.time()
    r = None
    for attempt in range(3):
        r = get_leaders(force=True)
        line = (f"[kr-movers] {r['status']} · {r['trade_date']} · {len(r['items'])}종목 · "
                f"클러스터 {len(r['clusters'])} · 개별이슈 {len(r['idiosyncratic'])}"
                + (f" · error={r['error']}" if r["error"] else "") + (f" (시도 {attempt + 1})" if attempt else ""))
        print(line, flush=True)
        if r["status"] == "ok":
            break
        if attempt < 2:
            time.sleep(120)
    status = "ok" if r and r["status"] == "ok" else ("partial" if r and r["items"] else "error")
    record_run("snapshot_kr_movers", status,
               f"{r['status']} · {r['trade_date']} · {len(r['items'])}종목" + (f" · {r['error']}" if r and r.get("error") else ""),
               int((time.time() - t0) * 1000))

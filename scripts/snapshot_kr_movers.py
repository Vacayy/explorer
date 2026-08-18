"""전일 국장 거래대금 상위 일별 스냅샷 (launchd: 평일 16:20 KST, D-108).

일별로 쌓아야 '신규 진입'(직전 스냅샷 대비) 판정이 가능하다. 멱등 — 같은 날 재실행하면 갱신.
LLM 0콜. FDR 1콜이라 수 초.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.kr_movers import get_leaders

if __name__ == "__main__":
    init_db()
    r = get_leaders(force=True)
    print(f"[kr-movers] {r['status']} · {r['trade_date']} · {len(r['items'])}종목 · "
          f"클러스터 {len(r['clusters'])} · 개별이슈 {len(r['idiosyncratic'])}"
          + (f" · error={r['error']}" if r["error"] else ""))

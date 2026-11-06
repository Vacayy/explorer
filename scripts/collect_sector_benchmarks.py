"""섹터 대표지수 일별 수집 (ia-redesign §4.35, D-327-4, backend/pipeline/sector_benchmarks.py).

대표 ETF·코스피 종가(yfinance, 18콜 이하) + 섹터 계산 지수(stock_prices 저장분, 외부 호출 0). 모델 호출 없음.
launchd `sectorbench` — 평일 일별 시세(16:35·20:20) 뒤 16:55·20:35. 놓치면 따라잡기(D-249)가 보충한다.

  python scripts/collect_sector_benchmarks.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.sector_benchmarks import run


def main():
    init_db()
    r = run()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    deg = f" | degraded: {', '.join(r['degraded'])}" if r["degraded"] else ""
    print(f"[{ts}] sector_benchmarks — {r['rows']}행 · ETF {len(r['tickers'])} · 계산 지수 {r['index']['sectors']}섹터 {r['index']['rows']}행{deg}")
    return r


if __name__ == "__main__":
    from pipeline.ops import run_job
    run_job("sector_benchmarks", main)

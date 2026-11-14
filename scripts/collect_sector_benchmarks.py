"""섹터 대표지수 일별 수집 (ia-redesign §4.35, D-327-4, backend/pipeline/sector_benchmarks.py).

대표 ETF·코스피 종가(yfinance, 18콜 이하) + 섹터 계산 지수(stock_prices 저장분, 외부 호출 0). 모델 호출 없음.
미국 섹터(§4.36): ETF 24 + SPY 종가(일괄 1~2콜) · 팔로우 종목 Yahoo 업종(없거나 30일 지난 것만) · 팔로우 시세 꼬리(일괄 1~2콜).
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
    us = r.get("us") or {}
    us_line = (f" · 미국 ETF {len(us['etf']['tickers'])} {us['etf']['rows']}행 · 업종 {us['sectors']['fetched']}/{us['sectors']['due']}"
               f" · 팔로우 시세 {us['follow_prices']['tickers']}종목 {us['follow_prices']['rows']}행") if "etf" in us else ""
    print(f"[{ts}] sector_benchmarks — {r['rows']}행 · ETF {len(r['tickers'])} · 계산 지수 {r['index']['sectors']}섹터 {r['index']['rows']}행{us_line}{deg}")
    return r


if __name__ == "__main__":
    from pipeline.ops import run_job
    run_job("sector_benchmarks", main)

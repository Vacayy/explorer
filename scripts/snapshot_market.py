"""시장 국면 일별 스냅샷 (market regime, D-076, docs/specs/market-regime.md).

F&G·VIX·S&P·KOSPI·VKOSPI(폴백 실현변동성)를 fetch → market_indicators 멱등 적재.
스파크라인 히스토리 + 당일 값. EOD 1회 실행 권장.

크론 예시 (평일 16:20 — ingest_prices 16:10 직후, KOSPI 종가 반영):
  20 16 * * 1-5 cd <PROJECT_DIR> && ./.venv/bin/python scripts/snapshot_market.py >> logs/ingest.log 2>&1

사용법:
  python scripts/snapshot_market.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.market_regime import snapshot_market


def main():
    init_db()
    result = snapshot_market()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    deg = f" | degraded: {', '.join(result['degraded'])}" if result["degraded"] else ""
    print(f"[{ts}] snapshot_market — {result['rows']}행 · {', '.join(result['indicators'])}{deg}")


if __name__ == "__main__":
    main()

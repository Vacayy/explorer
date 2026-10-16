"""발견(시장 분석)용 시세 이력 `market_history.sqlite`를 매일 새로 게시한다 (D-177 저장소, D-220 스케줄).

launchd `dev.explorer.history`가 평일 20:40(일별 시세 20:20 재수집 뒤)에 실행한다. 모델 호출 0.
`collect_market_history.py`의 plan → collect → publish를 그대로 쓴다 — 분할·병합 조정이 전 기간에 일관되도록
매번 전 종목 전체 기간을 다시 받고(이어붙이지 않음), 기준일은 stock_prices의 최신 거래일이다.

- 작업 폴더 `logs/market-history/<기준일>`: 노트북이 잠들어 중단돼도 다음 실행이 같은 폴더에서 이어 받는다.
- 이미 그 기준일로 게시돼 있으면 건너뛴다(멱등).
- 수집 성공 종목이 직전 게시본의 90% 미만이면 게시하지 않는다(공급자 장애가 발견 대상을 줄이지 않게).
- 게시 뒤 다른 기준일의 작업 폴더는 지운다(폴더당 수백 MB).

  python scripts/refresh_market_history.py            # 최신 거래일 기준
"""
import json
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))
sys.path.insert(0, str(PROJECT / "scripts"))

import collect_market_history as history  # noqa: E402
from pipeline.ops import record_run  # noqa: E402

SOURCE = PROJECT / "backend/db/stock_explorer.db"
DESTINATION = SOURCE.with_name("market_history.sqlite")
ROOT = PROJECT / "logs/market-history"
MIN_COVERAGE = 0.9


def _published() -> tuple[str | None, int]:
    if not DESTINATION.exists():
        return None, 0
    with closing(history.readonly(DESTINATION)) as db:
        as_of = json.loads(db.execute("SELECT value FROM metadata WHERE key='as_of'").fetchone()[0])
        return as_of, db.execute("SELECT count(*) FROM coverage WHERE status='collected'").fetchone()[0]


def main() -> int:
    started = time.monotonic()
    with closing(history.readonly(SOURCE)) as db:
        as_of = db.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    published_as_of, published_codes = _published()
    if published_as_of == as_of:
        print(f"[history] {as_of} 이미 게시됨 — 건너뜀")
        record_run("market_history", "skipped", f"{as_of} 이미 게시됨")
        return 0
    folder = ROOT / as_of
    try:
        history.plan(SOURCE, folder)
        history.collect(folder)
        with closing(sqlite3.connect(folder / "staging.sqlite")) as stage:
            collected = stage.execute("SELECT count(*) FROM tasks WHERE status='collected'").fetchone()[0]
        if collected < published_codes * MIN_COVERAGE:
            raise RuntimeError(f"수집 종목 {collected}개가 직전 게시본 {published_codes}개의 90% 미만 — 게시 보류")
        history.publish(folder, DESTINATION)
    except Exception as exc:  # noqa: BLE001
        summary = f"{as_of}: {type(exc).__name__}: {str(exc)[:200]}"
        print(f"[history] 실패 {summary}")
        record_run("market_history", "error", summary, int((time.monotonic() - started) * 1000))
        return 1
    for old in ROOT.iterdir():
        if old.is_dir() and old != folder:
            shutil.rmtree(old)
    summary = f"{published_as_of} → {as_of} · 종목 {collected}"
    print(f"[history] 게시 {summary}")
    record_run("market_history", "ok", summary, int((time.monotonic() - started) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())

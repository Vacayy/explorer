"""전 종목 주가 수집 (52주 신고가 스캔의 데이터 기반).

pykrx 시장 단위 엔드포인트는 KRX 로그인이 필요해져 FinanceDataReader 사용.

  python scripts/ingest_prices.py --daily
      FDR StockListing('KRX') 당일 스냅샷 → stock_prices upsert (장 마감 후 1회, cron)

  python scripts/ingest_prices.py --backfill [--days 380] [--limit N]
      종목별 FDR DataReader(네이버 소스)로 과거 일봉 백필. 재실행 가능(이미 충분한
      종목은 건너뜀). 전 종목 1회 실행에 수십 분 소요 — 백그라운드 실행 권장.
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection, init_db


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):  # NaN
        return None
    return v


def ingest_daily():
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    conn = get_connection()
    today = date.today().isoformat()
    n = 0
    for _, r in df.iterrows():
        code = str(r["Code"]).zfill(6)
        if not _clean(r.get("Close")):
            continue
        conn.execute(
            """INSERT INTO stock_prices (stock_code, trade_date, open, high, low, close, volume, market_cap, shares)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 market_cap=excluded.market_cap, shares=excluded.shares""",
            (code, today, _clean(r.get("Open")), _clean(r.get("High")), _clean(r.get("Low")),
             _clean(r.get("Close")), _clean(r.get("Volume")), _clean(r.get("Marcap")), _clean(r.get("Stocks"))),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"[daily] {today}: {n}종목 upsert")


def backfill(days: int, limit: int | None):
    import FinanceDataReader as fdr

    start = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()
    codes = [r["stock_code"] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM companies WHERE stock_code IS NOT NULL AND stock_code != ''"
    ).fetchall()]

    # 이미 충분한 히스토리가 있는 종목은 스킵 (재실행 안전)
    have = {r["stock_code"]: r["n"] for r in conn.execute(
        "SELECT stock_code, count(*) n FROM stock_prices WHERE trade_date >= ? GROUP BY stock_code",
        (start,),
    ).fetchall()}
    todo = [c for c in codes if have.get(c, 0) < 200]
    if limit:
        todo = todo[:limit]
    print(f"[backfill] 대상 {len(todo)}/{len(codes)}종목, {start}~")

    done = failed = 0
    for i, code in enumerate(todo):
        try:
            df = fdr.DataReader(code, start)
            rows = [
                (code, idx.date().isoformat(), _clean(r.get("Open")), _clean(r.get("High")),
                 _clean(r.get("Low")), _clean(r.get("Close")), _clean(r.get("Volume")))
                for idx, r in df.iterrows() if _clean(r.get("Close"))
            ]
            conn.executemany(
                """INSERT INTO stock_prices (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume""",
                rows,
            )
            conn.commit()
            done += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  실패 {code}: {e}")
        if (i + 1) % 100 == 0:
            print(f"  진행 {i + 1}/{len(todo)} (실패 {failed})")
        time.sleep(0.05)  # 네이버 소스 rate limit 배려

    conn.close()
    print(f"[backfill] 완료 {done}, 실패 {failed}")


def _refresh_valuation():
    """전종목 PER·ROE 갱신 (네이버 시세) — 소외 신호의 재료."""
    from services.market_valuation import fetch_market_valuation
    try:
        print("[valuation]", fetch_market_valuation())
    except Exception as e:
        print(f"[valuation] 실패: {str(e)[:100]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--days", type=int, default=380)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    init_db()
    if args.daily:
        ingest_daily()
        _refresh_valuation()  # 전종목 PER·ROE — 소외 신호 재료 (일 1회)
    elif args.backfill:
        backfill(args.days, args.limit)
    else:
        parser.error("--daily 또는 --backfill 지정")

"""전 종목 주가 수집 (52주 신고가 스캔의 데이터 기반).

pykrx 시장 단위 엔드포인트는 KRX 로그인이 필요해져 FinanceDataReader 사용.

  python scripts/ingest_prices.py --daily
      네이버 실시간 API의 KRX 정규장 일봉(체결일 기준, 마감분만) → stock_prices upsert (16:35 launchd),
      이어서 최근 10일 빈 날을 yfinance(KRX, 무조정)로 보충

  python scripts/ingest_prices.py --repair --since 2026-07-08
      yfinance(auto_adjust=False)로 해당 기간 일봉을 KRX 정규장 값으로 교체

  python scripts/ingest_prices.py --backfill [--days 380] [--limit N]
      종목별 FDR DataReader(네이버 소스)로 과거 일봉 백필. 재실행 가능(이미 충분한
      종목은 건너뜀). 전 종목 1회 실행에 수십 분 소요 — 백그라운드 실행 권장.
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection, init_db


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):  # NaN
        return None
    return v


KST = ZoneInfo("Asia/Seoul")
NAVER_RT = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
UPSERT = """INSERT INTO stock_prices (stock_code, trade_date, open, high, low, close, volume, market_cap, shares)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, trade_date) DO UPDATE SET
              open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, volume=excluded.volume,
              market_cap=COALESCE(excluded.market_cap, stock_prices.market_cap), shares=COALESCE(excluded.shares, stock_prices.shares)"""


def _kr_codes(conn) -> list[str]:
    return [r["stock_code"] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM companies WHERE stock_code GLOB '[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z]'")]


def ingest_daily(repair_days: int = 10):
    """KRX 정규장 일봉 — 네이버 실시간 API(closePrice=KRX, NXT는 별도 필드)를 장 마감 뒤 일괄 조회.

    날짜는 실행일이 아니라 각 시세의 체결 시각(localTradedAt)에서 가져온다. 체결일이 오늘 이전이거나, 오늘이면 KRX 정규장
    종료(15:30) 뒤 실행일 때만 저장한다 → 휴장일 실행은 직전 거래일을 같은 값으로 덮을 뿐 유령 행을 만들지 않고, 노트북이
    늦게 깨도 올바른 날짜로 들어가며, 장중 실행은 아무것도 쓰지 않는다. 이전 FDR StockListing 스냅샷은 16:10 'NXT 포함
    현재가'를 오늘 날짜로 박았다(2026-10-08 확인).
    marketStatus는 시간외 단일가(16:00–18:00)·NXT(~20:00) 동안 OPEN이라 판정에 쓰지 않는다 — 10-12·13은 16:35에
    2,600여 종목이 OPEN으로 걸러져 105종목만 저장됐다. 20:20 재실행(모든 세션 종료 뒤)이 같은 값을 덮어쓰고 바뀐 종가 수를 남긴다.
    """
    import requests

    conn = get_connection()
    codes = _kr_codes(conn)
    now = datetime.now(KST)
    today, closed = now.date().isoformat(), now.strftime("%H%M") >= "1530"
    rows, skipped, failed = [], {}, 0
    for k in range(0, len(codes), 200):
        batch = codes[k:k + 200]
        try:
            r = requests.get(NAVER_RT.format(codes=",".join(batch)), headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            datas = r.json().get("datas") or []
        except Exception as e:  # noqa: BLE001
            failed += len(batch)
            print(f"[daily] 배치 실패 {k}: {type(e).__name__}")
            continue
        for d in datas:
            num = lambda key: _clean(float(d[key])) if d.get(key) not in (None, "", "-") else None  # noqa: E731
            close, cap = num("closePriceRaw"), num("marketValueFullRaw")
            day = (d.get("localTradedAt") or "")[:10]
            if not close or not day:
                continue
            if day == today and not closed:
                skipped["장중"] = skipped.get("장중", 0) + 1
                continue
            rows.append((d["itemCode"], day, num("openPriceRaw"), num("highPriceRaw"), num("lowPriceRaw"), close,
                         num("accumulatedTradingVolumeRaw"), cap, round(cap / close) if cap and close else None))
        time.sleep(0.1)
    before = {(r[0], r[1]): r[2] for r in conn.execute(
        "SELECT stock_code, trade_date, close FROM stock_prices WHERE trade_date IN (%s)" % ",".join("?" * len({r[1] for r in rows})),
        sorted({r[1] for r in rows}))} if rows else {}
    changed = sum(1 for r in rows if (r[0], r[1]) in before and before[(r[0], r[1])] != r[5])
    conn.executemany(UPSERT, rows)
    conn.commit()
    days = sorted({r[1] for r in rows})
    print(f"[daily] KRX 종가 {len(rows)}종목 upsert · 거래일 {days} · 기존과 다른 종가 {changed} · 건너뜀 {skipped or '-'} · 실패 {failed}")
    if skipped and not rows:
        print("[daily] 장이 아직 마감되지 않아 저장하지 않았습니다(장중 실행). 다음 실행 또는 --repair가 채웁니다.")
    if repair_days:
        # 최근 거래일 중 비어 있는 (종목, 날짜)만 yfinance로 보충 — 전 종목을 매일 부르면 속도 제한에 걸린다.
        # 거래일은 KOSPI 지수 일봉(index_kospi) 달력, 대상은 최근 30일에 시세가 있는 종목. 일별 수집이 통째로 빠진 날도 잡힌다.
        since = (date.today() - timedelta(days=repair_days)).isoformat()
        days_ = [r[0] for r in conn.execute("SELECT DISTINCT snapshot_date FROM market_indicators WHERE indicator='index_kospi' "
                                            "AND snapshot_date >= ? AND snapshot_date < ?", (since, today))]
        have = {(r[0], r[1]) for r in conn.execute("SELECT stock_code, trade_date FROM stock_prices WHERE trade_date >= ?", (since,))}
        active = {r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM stock_prices WHERE trade_date >= ?",
                                             ((date.today() - timedelta(days=30)).isoformat(),))}
        gaps = sorted({c for c in active for d in days_ if (c, d) not in have})
        print(f"[daily] 최근 {repair_days}일 빈 날 있는 종목 {len(gaps)}")
        conn.close()
        if gaps:
            repair(repair_days, only_missing=True, codes=gaps)
    else:
        conn.close()
    status = "error" if failed and not rows else "partial" if failed else "ok"
    return {"upsert": len(rows), "days": ",".join(days), "changed": changed, "failed": failed, "status": status}


def _yf_batch(yf, tickers: list[str], start: str, end: str, tries: int = 4):
    """yfinance 묶음 다운로드 — 속도 제한이면 30·60·120초 쉬고 재시도."""
    for k in range(tries):
        df = yf.download(tickers, start=start, end=end, auto_adjust=False, progress=False, group_by="ticker", threads=False)
        got = set(df.columns.get_level_values(0)) if not df.empty else set()
        if got or k == tries - 1:
            return df, got
        time.sleep(30 * 2 ** k)
    return df, got


def repair(days: int, only_missing: bool = False, since: str | None = None, codes: list[str] | None = None) -> set[str]:
    """yfinance(auto_adjust=False = KRX 정규장 종가, 배당 조정 없음)로 최근 일봉을 채우거나 교체. 갱신한 종목 집합을 돌려준다.

    only_missing=True면 비어 있는 (종목, 날짜)만 넣는다 — 일별 수집이 빠진 날(노트북 수면 등) 보정용.
    시장 구분이 틀린 종목은 .KS↔.KQ를 한 번 바꿔 다시 시도한다.
    """
    import yfinance as yf

    start = since or (date.today() - timedelta(days=days)).isoformat()
    end = date.today().isoformat()        # 오늘은 제외(장중 미확정) — 오늘 종가는 네이버 일별 수집이 담당
    conn = get_connection()
    markets = {r["stock_code"]: r["market"] or "" for r in conn.execute(
        "SELECT stock_code, market FROM companies WHERE stock_code GLOB '[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z]'")}
    if codes:
        markets = {c: markets.get(c, "") for c in codes}
    have = {(r["stock_code"], r["trade_date"]) for r in conn.execute(
        "SELECT stock_code, trade_date FROM stock_prices WHERE trade_date >= ?", (start,))} if only_missing else set()
    suffix = lambda c, m, flip=False: f"{c}.{('KS' if 'KOSDAQ' in m.upper() else 'KQ') if flip else ('KQ' if 'KOSDAQ' in m.upper() else 'KS')}"  # noqa: E731
    done, n = set(), 0
    for flip in (False, True):
        todo = [c for c in markets if c not in done]
        tickers = {suffix(c, markets[c], flip): c for c in todo}
        names = list(tickers)
        for k in range(0, len(names), 100):
            batch = names[k:k + 100]
            try:
                df, got = _yf_batch(yf, batch, start, end)
            except Exception as e:  # noqa: BLE001
                print(f"[repair] 배치 실패 {k}: {type(e).__name__}")
                continue
            rows = []
            for t in batch:
                if t not in got:
                    continue
                sub = df[t].dropna(subset=["Close"])
                if sub.empty:
                    continue
                done.add(tickers[t])
                for idx, r in sub.iterrows():
                    key = (tickers[t], idx.date().isoformat())
                    if only_missing and key in have:
                        continue
                    vals = [_clean(r.get(c)) for c in ("Open", "High", "Low", "Close", "Volume")]
                    if not vals[3] or vals[4] == 0:      # 거래 없는 날(정지 등)은 건너뜀
                        continue
                    rows.append((*key, *[round(v) if v is not None else None for v in vals], None, None))
            conn.executemany(UPSERT, rows)
            conn.commit()
            n += len(rows)
            time.sleep(2)
    filled = fill_market_cap(conn, start)
    conn.close()
    print(f"[repair] {start}~ {'빈 날만' if only_missing else '교체'} {n}행 · 갱신 {len(done)}/{len(markets)}종목 · 시총 보충 {filled}행")
    return done


def fill_market_cap(conn, since: str) -> int:
    """시가총액·주식 수가 빈 행(yfinance 보충분)을 같은 종목의 직전 주식 수 × 그날 종가로 채운다.

    yfinance에는 시총·주식 수가 없어 보충 행이 비어 있었고, 발견 검색이 기준일 시총을 읽어 '-'·시총 조건 미평가가 됐다
    (2026-10-14 확인: 10-12·13 2,755종목 중 105종목만 시총 보유). 주식 수는 증자·분할이 없으면 며칠 사이 그대로다.
    """
    cur = conn.execute("""UPDATE stock_prices AS s SET
          shares = (SELECT p.shares FROM stock_prices p WHERE p.stock_code = s.stock_code AND p.trade_date < s.trade_date
                    AND p.shares IS NOT NULL ORDER BY p.trade_date DESC LIMIT 1)
        WHERE s.trade_date >= ? AND s.shares IS NULL AND s.close IS NOT NULL""", (since,))
    conn.execute("""UPDATE stock_prices SET market_cap = shares * close
        WHERE trade_date >= ? AND market_cap IS NULL AND shares IS NOT NULL AND close IS NOT NULL""", (since,))
    conn.commit()
    return cur.rowcount


def verify(sample: list[str] | None = None) -> list[str]:
    """저장된 직전 거래일 종가가 네이버 KRX 전일 종가(현재가−전일대비)와 다른 종목 목록."""
    import requests

    conn = get_connection()
    codes = sample or _kr_codes(conn)
    bad = []
    for k in range(0, len(codes), 200):
        datas = requests.get(NAVER_RT.format(codes=",".join(codes[k:k + 200])), headers={"User-Agent": "Mozilla/5.0"},
                             timeout=15).json().get("datas") or []
        for d in datas:
            try:
                prev = float(d["closePriceRaw"]) - float(d["compareToPreviousClosePriceRaw"])
            except (KeyError, TypeError, ValueError):
                continue
            day = (d.get("localTradedAt") or "")[:10]
            row = conn.execute("SELECT close FROM stock_prices WHERE stock_code=? AND trade_date<? ORDER BY trade_date DESC LIMIT 1",
                               (d["itemCode"], day)).fetchone()
            if row and abs((row["close"] or 0) - prev) > 0.5:
                bad.append(d["itemCode"])
        time.sleep(0.1)
    conn.close()
    print(f"[verify] 직전 거래일 종가 불일치 {len(bad)}/{len(codes)}종목")
    return bad


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
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--since", default=None)
    parser.add_argument("--codes", default=None, help="쉼표 구분 종목코드 (repair 대상 제한)")
    parser.add_argument("--verify", action="store_true", help="직전 거래일 종가를 네이버 KRX 값과 대조")
    parser.add_argument("--fix", action="store_true", help="--verify 불일치 종목을 --since부터 다시 교체")
    parser.add_argument("--fill-cap", action="store_true", help="--since부터 시총·주식 수 빈 행을 직전 주식 수로 채움")
    args = parser.parse_args()

    init_db()
    if args.daily:
        from pipeline.ops import run_job
        run_job("prices", ingest_daily)  # job_runs 기록 — 관리자 화면에서 실행 이력이 보이게 (D-222)
        _refresh_valuation()  # 전종목 PER·ROE — 소외 신호 재료 (일 1회)
    elif args.repair:
        repair(args.days, since=args.since, codes=args.codes.split(",") if args.codes else None)
    elif args.verify:
        bad = verify()
        if bad and args.fix:
            repair(args.days, since=args.since, codes=bad)
            verify(bad)
    elif args.fill_cap:
        conn = get_connection()
        print(f"[fill-cap] {args.since} 이후 {fill_market_cap(conn, args.since)}행")
        conn.close()
    elif args.backfill:
        backfill(args.days, args.limit)
    else:
        parser.error("--daily, --repair 또는 --backfill 지정")

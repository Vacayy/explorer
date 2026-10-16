"""미국 종목 데이터 레이어 (docs/specs/us-dossier.md) — yfinance 캐시.

- 시세: us_prices (EOD 일별 OHLCV, 컬럼명 stock_prices 호환 → technicals 재사용)
- 재무·추정치: us_fundamentals (info/income/cashflow/analyst estimates 스냅샷, 24h 캐시)
- US 기업 해소: transcript_follow(ticker↔entity_id) 정본, 없으면 entities 이름 매칭
모든 외부 조회는 캐시 우선(peer_metrics 패턴). 팔로우된 US 티커만 다룬다(전체 시장 안 긁음).
"""
import json

from database import get_connection

_PRICE_TTL_HOURS = 20        # 시세 재조회 간격 (EOD)
_FUND_TTL_HOURS = 24         # 재무·추정치 재조회 간격
BENCHMARK = "SPY"            # 추세 렌즈 상대강도 기준


def resolve_us(conn, ticker: str):
    """티커 → (entity_id, name). transcript_follow 우선, 없으면 entities 이름 매칭."""
    t = (ticker or "").upper()
    row = conn.execute(
        "SELECT entity_id, company_name FROM transcript_follow WHERE ticker=?", (t,)).fetchone()
    if row and row["entity_id"]:
        return row["entity_id"], row["company_name"]
    row = conn.execute(
        "SELECT id, name FROM entities WHERE type='company' AND upper(name)=? LIMIT 1", (t,)).fetchone()
    if row:
        return row["id"], row["name"]
    return None, (row["company_name"] if row else t)


# ── 시세 (us_prices) ────────────────────────────────────────────────────────

def _prices_fresh(conn, ticker: str) -> bool:
    r = conn.execute(
        "SELECT max(fetched_at) f FROM us_prices WHERE stock_code=?", (ticker,)).fetchone()
    if not r or not r["f"]:
        return False
    age = conn.execute("SELECT (julianday('now') - julianday(?)) * 24 h", (r["f"],)).fetchone()["h"]
    return age is not None and age < _PRICE_TTL_HOURS


def fetch_prices(ticker: str, period: str = "2y", force: bool = False) -> int:
    """yfinance history → us_prices 멱등 적재. 신선하면 skip. 반환=적재 행수(skip시 0)."""
    ticker = ticker.upper()
    conn = get_connection()
    if not force and _prices_fresh(conn, ticker):
        conn.close()
        return 0
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    except Exception:
        conn.close()
        return 0
    n = 0
    for idx, row in hist.iterrows():
        if _f(row.get("Close")) is None:  # 장중 미완성·NaN 봉은 저장하지 않는다(차트·전략 계산이 깨진다)
            continue
        d = idx.date().isoformat()
        conn.execute("""
            INSERT INTO us_prices (stock_code, trade_date, open, high, low, close, volume, fetched_at)
            VALUES (?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(stock_code, trade_date) DO UPDATE SET
              close=excluded.close, volume=excluded.volume, high=excluded.high,
              low=excluded.low, open=excluded.open, fetched_at=excluded.fetched_at
        """, (ticker, d, _f(row.get("Open")), _f(row.get("High")), _f(row.get("Low")),
              _f(row.get("Close")), _f(row.get("Volume"))))
        n += 1
    conn.commit()
    conn.close()
    return n


def price_status(conn, ticker: str) -> dict:
    """us_prices 보유 현황. 화면의 '시세 수집' 버튼이 무엇을 할지 정하는 사실(행 수·최신 거래일·수집 시각·묵음)."""
    ticker = ticker.upper()
    row = conn.execute("SELECT COUNT(*) n, MIN(trade_date) first, MAX(trade_date) last, MAX(fetched_at) fetched FROM us_prices WHERE stock_code=?",
                       (ticker,)).fetchone()
    latest_any = conn.execute("SELECT MAX(trade_date) FROM us_prices").fetchone()[0]
    stale_days = None
    if row["last"] and latest_any:
        stale_days = conn.execute("SELECT CAST(julianday(?) - julianday(?) AS INTEGER)", (latest_any, row["last"])).fetchone()[0]
    return {"ticker": ticker, "rows": row["n"], "first_date": row["first"], "last_date": row["last"],
            "fetched_at": (row["fetched"].replace(" ", "T") + "Z") if row["fetched"] else None,
            "latest_available": latest_any, "stale_days": stale_days,
            "state": "missing" if not row["n"] else ("stale" if (stale_days or 0) > 3 else "fresh")}


class PriceCollectError(RuntimeError):
    pass


def collect_prices(ticker: str, period: str = "2y") -> dict:
    """버튼 주도 수집(D-100): yfinance history를 강제로 받아 us_prices에 멱등 적재. 실패는 조용히 0이 아니라 예외로."""
    ticker = ticker.upper()
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    except Exception as exc:  # 망·티커 오류를 화면에 그대로 보인다
        raise PriceCollectError(f"yfinance 조회 실패: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if hist is None or hist.empty:
        raise PriceCollectError(f"yfinance에 {ticker} 시세가 없습니다. 티커를 확인해 주세요.")
    conn = get_connection()
    try:
        n = 0
        for idx, row in hist.iterrows():
            if _f(row.get("Close")) is None:  # 장중 미완성·NaN 봉 제외
                continue
            conn.execute("""
                INSERT INTO us_prices (stock_code, trade_date, open, high, low, close, volume, fetched_at)
                VALUES (?,?,?,?,?,?,?, datetime('now'))
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                  close=excluded.close, volume=excluded.volume, high=excluded.high,
                  low=excluded.low, open=excluded.open, fetched_at=excluded.fetched_at
            """, (ticker, idx.date().isoformat(), _f(row.get("Open")), _f(row.get("High")), _f(row.get("Low")),
                  _f(row.get("Close")), _f(row.get("Volume"))))
            n += 1
        conn.commit()
        status = price_status(conn, ticker)
    finally:
        conn.close()
    return {**status, "collected_rows": n, "source": "yfinance", "period": period}


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ── 재무·추정치 (us_fundamentals) ────────────────────────────────────────────

def _latest(df, name):
    """yfinance 재무 DataFrame에서 계정명 최신(첫 열) 값."""
    try:
        s = df.loc[name]
        return _f(s.iloc[0]) if len(s) else None
    except Exception:
        return None


def _build_fundamentals(ticker: str) -> dict | None:
    import yfinance as yf
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if not info.get("currentPrice") and not info.get("marketCap"):
        return None  # 유효하지 않은 티커
    cf = getattr(t, "cashflow", None)
    inc = getattr(t, "income_stmt", None)
    ocf = _latest(cf, "Operating Cash Flow") if cf is not None else None
    fcf = _latest(cf, "Free Cash Flow") if cf is not None else None
    capex = _latest(cf, "Capital Expenditure") if cf is not None else None
    revenue = _latest(inc, "Total Revenue") if inc is not None else None
    net_income = _latest(inc, "Net Income") if inc is not None else None

    def estimates():
        out = {}
        try:
            er = t.eps_revisions
            for p in ("0y", "+1y"):
                if p in er.index:
                    r = er.loc[p]
                    out.setdefault("revisions", {})[p] = {
                        "up30": int(r.get("upLast30days") or 0), "down30": int(r.get("downLast30days") or 0)}
        except Exception:
            pass
        try:
            et = t.eps_trend
            if "+1y" in et.index:
                r = et.loc["+1y"]
                out["eps_trend_1y"] = {"current": _f(r.get("current")), "d90": _f(r.get("90daysAgo"))}
        except Exception:
            pass
        try:
            ee = t.earnings_estimate
            if "+1y" in ee.index:
                r = ee.loc["+1y"]
                out["earnings_1y"] = {"avg": _f(r.get("avg")), "growth": _f(r.get("growth")),
                                      "analysts": int(r.get("numberOfAnalysts") or 0)}
        except Exception:
            pass
        try:
            out["price_targets"] = {k: _f(v) for k, v in (t.analyst_price_targets or {}).items()}
        except Exception:
            pass
        return out

    quality = round(ocf / net_income, 2) if (ocf and net_income and net_income > 0) else None
    return {
        "price": _f(info.get("currentPrice")), "market_cap": _f(info.get("marketCap")),
        "fwd_pe": _f(info.get("forwardPE")), "trailing_pe": _f(info.get("trailingPE")),
        "fwd_eps": _f(info.get("forwardEps")), "trailing_eps": _f(info.get("trailingEps")),
        "revenue": revenue, "net_income": net_income,
        "ocf": ocf, "fcf": fcf, "capex": capex, "earnings_quality": quality,
        "estimates": estimates(),
    }


def get_fundamentals(ticker: str, force: bool = False) -> dict | None:
    """us_fundamentals 캐시(24h). 미스·만료면 yfinance 조회 후 적재."""
    ticker = ticker.upper()
    conn = get_connection()
    row = conn.execute(
        "SELECT data_json, (julianday('now') - julianday(fetched_at)) * 24 age "
        "FROM us_fundamentals WHERE ticker=?", (ticker,)).fetchone()
    if row and not force and row["age"] is not None and row["age"] < _FUND_TTL_HOURS:
        conn.close()
        return json.loads(row["data_json"])
    try:
        data = _build_fundamentals(ticker)
    except Exception:
        data = None
    if data is None:
        conn.close()
        return json.loads(row["data_json"]) if row else None  # 조회 실패 시 구 캐시 폴백
    conn.execute("""
        INSERT INTO us_fundamentals (ticker, data_json, fetched_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(ticker) DO UPDATE SET data_json=excluded.data_json, fetched_at=excluded.fetched_at
    """, (ticker, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return data

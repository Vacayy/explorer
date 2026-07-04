"""Stock market data service — yfinance based.

All heavy imports (yfinance, pykrx) are LAZY to prevent server startup hang.
"""
from datetime import datetime
from database import get_connection
from config import CACHE_TTL_STOCK_PRICES
from services.cache_service import is_cached, set_cache


def _yf():
    """Lazy import yfinance."""
    import yfinance as yf
    return yf


def _get_market_suffix(stock_code: str) -> str:
    """Determine .KS (KOSPI) or .KQ (KOSDAQ) suffix for yfinance."""
    conn = get_connection()
    row = conn.execute("SELECT market FROM companies WHERE stock_code = ?", (stock_code,)).fetchone()
    conn.close()
    if row and row["market"] and "KOSDAQ" in row["market"].upper():
        return ".KQ"
    # Try yfinance to detect
    for suffix in [".KS", ".KQ"]:
        try:
            t = _yf().Ticker(f"{stock_code}{suffix}")
            info = t.info
            if info.get("regularMarketPrice") or info.get("currentPrice"):
                return suffix
        except Exception:
            pass
    return ".KS"


def fetch_stock_prices(stock_code: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch OHLCV + market cap data and cache."""
    cache_key = f"price:{stock_code}:{from_date}:{to_date}"
    if not is_cached(cache_key):
        _fetch_and_store_prices(stock_code, from_date, to_date)
        set_cache(cache_key, CACHE_TTL_STOCK_PRICES)

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume, market_cap
        FROM stock_prices
        WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date
        """,
        (stock_code, _fmt(from_date), _fmt(to_date)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_fundamentals(stock_code: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch PER/PBR/EPS/BPS and cache."""
    cache_key = f"fund:{stock_code}:{from_date}:{to_date}"
    if not is_cached(cache_key):
        _store_yfinance_fundamentals(stock_code)
        set_cache(cache_key, CACHE_TTL_STOCK_PRICES)

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT f.trade_date, sp.close, f.bps, f.per, f.pbr, f.eps, f.div_yield
        FROM fundamentals f
        LEFT JOIN stock_prices sp ON sp.stock_code = f.stock_code AND sp.trade_date = f.trade_date
        WHERE f.stock_code = ? AND f.trade_date >= ? AND f.trade_date <= ?
        ORDER BY f.trade_date
        """,
        (stock_code, _fmt(from_date), _fmt(to_date)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_pbr_bands(stock_code: str, from_date: str, to_date: str) -> dict:
    """Compute PBR band lines from historical data."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT f.trade_date, f.bps, f.pbr, sp.close
        FROM fundamentals f
        LEFT JOIN stock_prices sp ON sp.stock_code = f.stock_code AND sp.trade_date = f.trade_date
        WHERE f.stock_code = ? AND f.trade_date >= ? AND f.trade_date <= ?
          AND f.pbr IS NOT NULL AND f.pbr > 0 AND f.bps IS NOT NULL AND f.bps > 0
        ORDER BY f.trade_date
        """,
        (stock_code, _fmt(from_date), _fmt(to_date)),
    ).fetchall()
    conn.close()

    if len(rows) < 5:
        return {}

    pbr_values = sorted([r["pbr"] for r in rows if r["pbr"] and r["pbr"] > 0])
    import numpy as np
    percentiles = [10, 25, 50, 75, 90]
    pbr_levels = {f"pbr_p{p}": float(np.percentile(pbr_values, p)) for p in percentiles}

    bands: dict[str, list] = {k: [] for k in pbr_levels}
    bands["dates"] = []
    bands["close"] = []

    for r in rows:
        bands["dates"].append(r["trade_date"])
        bands["close"].append(r["close"])
        bps = r["bps"]
        for key, pbr_val in pbr_levels.items():
            bands[key].append(round(bps * pbr_val) if bps else None)

    return bands


def _fetch_and_store_prices(stock_code: str, from_date: str, to_date: str):
    """Fetch OHLCV + market cap from yfinance."""
    suffix = _get_market_suffix(stock_code)
    ticker = _yf().Ticker(f"{stock_code}{suffix}")

    fd = f"{from_date[:4]}-{from_date[4:6]}-{from_date[6:8]}"
    td = f"{to_date[:4]}-{to_date[4:6]}-{to_date[6:8]}"

    try:
        hist = ticker.history(start=fd, end=td)
    except Exception:
        return

    if hist is None or hist.empty:
        return

    # Get shares for market cap calculation
    shares = None
    try:
        info = ticker.info
        shares = info.get("sharesOutstanding")
        if not shares:
            mcap = info.get("marketCap")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if mcap and price and price > 0:
                shares = int(mcap / price)
    except Exception:
        pass

    conn = get_connection()
    for date_idx in hist.index:
        d = date_idx.strftime("%Y-%m-%d")
        row = hist.loc[date_idx]
        close = row.get("Close")
        if close is None or close != close:  # NaN check
            continue
        close_int = int(round(close))
        open_int = int(round(row.get("Open", 0))) or None
        high_int = int(round(row.get("High", 0))) or None
        low_int = int(round(row.get("Low", 0))) or None
        volume_int = int(row.get("Volume", 0)) or None
        mcap = int(close * shares) if shares and close else None

        conn.execute(
            """
            INSERT OR REPLACE INTO stock_prices
            (stock_code, trade_date, open, high, low, close, volume, market_cap, shares)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (stock_code, d, open_int, high_int, low_int, close_int, volume_int, mcap, shares),
        )
    conn.commit()
    conn.close()


def _store_yfinance_fundamentals(stock_code: str):
    """Store basic fundamentals from yfinance info."""
    try:
        suffix = _get_market_suffix(stock_code)
        ticker = _yf().Ticker(f"{stock_code}{suffix}")
        info = ticker.info

        per = info.get("trailingPE") or info.get("forwardPE")
        pbr = info.get("priceToBook")
        eps = info.get("trailingEps")
        bv = info.get("bookValue")

        if not any([per, pbr, eps, bv]):
            return

        today = datetime.now().strftime("%Y-%m-%d")
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO fundamentals
            (stock_code, trade_date, bps, per, pbr, eps, div_yield, dps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (stock_code, today, bv, per, pbr, eps, None, None),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return f if f != 0 else None
    except (ValueError, TypeError):
        return None


def _fmt(date_str: str) -> str:
    if "-" in date_str:
        return date_str
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

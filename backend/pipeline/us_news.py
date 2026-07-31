"""무버 종목별 US 원천 헤드라인 — yfinance `.news` 캐시 (D-097).

개별 종목 '왜'(예: BE +26% ← Mizuho 업그레이드·Q2 실적)를 채운다 — 브리핑의 스터디 후보를
실제 촉매로 바꾸는 층. 시장 레벨 담론(D-096)과 상보: 담론=왜 전체가 움직였나, 헤드라인=왜 이 종목이.

무키(yfinance). 종목별 6h 캐시(us_ticker_news). 실패는 조용히 빈 리스트(브리핑 안 죽인다).
"""
from database import get_connection

NEWS_TTL_HOURS = 6
NEWS_PER_TICKER = 3       # 종목당 노출 헤드라인 수
_RECENT_DAYS = 3          # 이보다 오래된 뉴스는 '왜'로 부적합


def _fresh(conn, ticker: str) -> bool:
    r = conn.execute("SELECT max(fetched_at) f FROM us_ticker_news WHERE ticker=?", (ticker,)).fetchone()
    if not r or not r["f"]:
        return False
    age = conn.execute("SELECT (julianday('now') - julianday(?)) * 24 h", (r["f"],)).fetchone()["h"]
    return age is not None and age < NEWS_TTL_HOURS


def _normalize(item: dict) -> dict | None:
    c = item.get("content", item) if isinstance(item, dict) else None
    if not isinstance(c, dict):
        return None
    title = c.get("title")
    if not title:
        return None
    prov = c.get("provider") or {}
    url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
    return {
        "title": title, "publisher": prov.get("displayName") if isinstance(prov, dict) else None,
        "published_at": c.get("pubDate"), "url": url or title,   # url 없으면 title로 PK 대체
        "summary": (c.get("summary") or c.get("description") or "")[:400],
    }


def fetch_news(ticker: str, force: bool = False) -> None:
    """yfinance .news → us_ticker_news 멱등 적재. 신선하면 skip. 실패는 무시."""
    conn = get_connection()
    if not force and _fresh(conn, ticker):
        conn.close()
        return
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).news or []
    except Exception:
        conn.close()
        return
    for item in raw:
        n = _normalize(item)
        if not n:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO us_ticker_news (ticker, url, title, publisher, published_at, summary, fetched_at) "
            "VALUES (?,?,?,?,?,?, datetime('now'))",
            (ticker, n["url"], n["title"], n["publisher"], n["published_at"], n["summary"]))
    conn.commit()
    conn.close()


def get_news(conn, ticker: str, limit: int = NEWS_PER_TICKER) -> list[dict]:
    """최근 며칠 내 헤드라인 최신순. (fetch_news로 적재된 캐시 읽기)"""
    rows = conn.execute(
        "SELECT title, publisher, published_at, url, summary FROM us_ticker_news "
        "WHERE ticker=? AND (published_at IS NULL OR published_at >= datetime('now', ?)) "
        "ORDER BY published_at DESC LIMIT ?",
        (ticker, f"-{_RECENT_DAYS} days", limit)).fetchall()
    return [dict(r) for r in rows]

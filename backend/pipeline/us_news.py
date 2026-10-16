"""무버 종목별 US 원천 헤드라인 — Yahoo 종목 RSS 캐시 (D-097).

개별 종목 '왜'(예: BE +26% ← Mizuho 업그레이드·Q2 실적)를 채운다 — 브리핑의 스터디 후보를
실제 촉매로 바꾸는 층. 시장 레벨 담론(D-096)과 상보: 담론=왜 전체가 움직였나, 헤드라인=왜 이 종목이.

무키. 종목별 캐시(us_ticker_news). yfinance `.news`는 2026-09-30부터 엔드포인트 404로 빈 목록만 돌려줘
RSS로 바꿨다. 수집 실패는 예외로 올린다 — 호출부(브리핑)가 실패 종목을 모아 잡 상태에 남긴다.
"""
import email.utils
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

from database import get_connection

NEWS_TTL_HOURS = 24      # 하루 1회 — 브리핑 케이던스에 맞춤(마감 후 크론/수동 버튼이 force)
NEWS_PER_TICKER = 3       # 종목당 노출 헤드라인 수
_RECENT_DAYS = 3          # 이보다 오래된 뉴스는 '왜'로 부적합
RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def _fresh(conn, ticker: str) -> bool:
    r = conn.execute("SELECT max(fetched_at) f FROM us_ticker_news WHERE ticker=?", (ticker,)).fetchone()
    if not r or not r["f"]:
        return False
    age = conn.execute("SELECT (julianday('now') - julianday(?)) * 24 h", (r["f"],)).fetchone()["h"]
    return age is not None and age < NEWS_TTL_HOURS


def _parse(xml_text: str) -> list[dict]:
    out = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        url = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        published = email.utils.parsedate_to_datetime(pub).strftime("%Y-%m-%dT%H:%M:%SZ") if pub else None
        host = urlparse(url).netloc.removeprefix("www.")
        out.append({"title": title, "url": url or title, "published_at": published,   # url 없으면 title로 PK 대체
                    "publisher": host or None, "summary": (item.findtext("description") or "").strip()[:400]})
    return out


def fetch_news(ticker: str, force: bool = False) -> int | None:
    """Yahoo 종목 RSS → us_ticker_news 멱등 적재. 신선하면 None, 아니면 받은 건수. HTTP·파싱 실패는 raise."""
    conn = get_connection()
    try:
        if not force and _fresh(conn, ticker):
            return None
        r = requests.get(RSS_URL.format(ticker=ticker), headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        items = _parse(r.text)
        for n in items:
            conn.execute(
                "INSERT OR REPLACE INTO us_ticker_news (ticker, url, title, publisher, published_at, summary, fetched_at) "
                "VALUES (?,?,?,?,?,?, datetime('now'))",
                (ticker, n["url"], n["title"], n["publisher"], n["published_at"], n["summary"]))
        conn.commit()
        return len(items)
    finally:
        conn.close()


def get_news(conn, ticker: str, limit: int = NEWS_PER_TICKER) -> list[dict]:
    """최근 며칠 내 헤드라인 최신순. (fetch_news로 적재된 캐시 읽기)"""
    rows = conn.execute(
        "SELECT title, publisher, published_at, url, summary FROM us_ticker_news "
        "WHERE ticker=? AND (published_at IS NULL OR published_at >= datetime('now', ?)) "
        "ORDER BY published_at DESC LIMIT ?",
        (ticker, f"-{_RECENT_DAYS} days", limit)).fetchall()
    return [dict(r) for r in rows]

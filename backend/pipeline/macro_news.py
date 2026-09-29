"""미국 주요 매체·Fed 헤드라인 — 어젯밤 매크로 이슈 재료 (D-206, docs/specs/us-briefing.md).

무키 RSS. 본문은 대부분 유료 벽이라 **제목+요약만** 적재한다(인용 검증도 이 두 필드에 대해서만).
피드별 실패는 결과로 돌려준다 — 브리핑이 '어느 매체가 빠졌나'를 화면에 밝힐 수 있게(조용한 fallback 금지).
WSJ·Reuters·AP·BLS·재무부는 2026-09-29 실측에서 피드 폐지·차단이라 목록에 없다.
"""
from concurrent.futures import ThreadPoolExecutor

from database import get_connection
from services.blog_service import _entry_published, _parse_feed

FEEDS = [
    {"key": "bloomberg_markets", "publisher": "Bloomberg", "kind": "news",
     "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"key": "bloomberg_economics", "publisher": "Bloomberg", "kind": "news",
     "url": "https://feeds.bloomberg.com/economics/news.rss"},
    {"key": "cnbc_economy", "publisher": "CNBC", "kind": "news",
     "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
    {"key": "cnbc_finance", "publisher": "CNBC", "kind": "news",
     "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"key": "nyt_business", "publisher": "New York Times", "kind": "news",
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"},
    {"key": "nyt_economy", "publisher": "New York Times", "kind": "news",
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"},
    {"key": "nyt_politics", "publisher": "New York Times", "kind": "news",
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"},
    {"key": "politico_politics", "publisher": "Politico", "kind": "news",
     "url": "https://rss.politico.com/politics-news.xml"},
    {"key": "marketwatch_top", "publisher": "MarketWatch", "kind": "news",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"key": "wapo_business", "publisher": "Washington Post", "kind": "news",
     "url": "https://feeds.washingtonpost.com/rss/business"},
    {"key": "fed_press", "publisher": "Federal Reserve", "kind": "official",
     "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"key": "fed_speeches", "publisher": "Federal Reserve", "kind": "official",
     "url": "https://www.federalreserve.gov/feeds/speeches.xml"},
]
# Fed 보도자료 중 개별 은행 인가·제재는 매크로 이슈가 아니다
_SKIP_CATEGORIES = {"Orders on Banking Applications", "Enforcement Actions"}
SUMMARY_CHARS = 500
RETAIN_DAYS = 14


def _strip_html(text: str) -> str:
    if "<" not in (text or ""):
        return (text or "").strip()
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


def _fetch_one(feed: dict) -> tuple[dict, list[dict] | None, str | None]:
    try:
        parsed = _parse_feed(feed["url"])
    except Exception as e:  # noqa: BLE001
        return feed, None, f"{type(e).__name__}"
    if not parsed.entries:
        return feed, None, "항목 없음"
    rows = []
    for e in parsed.entries:
        if e.get("category") in _SKIP_CATEGORIES:
            continue
        url, title = e.get("link"), _strip_html(e.get("title", ""))
        if not url or not title:
            continue
        rows.append({"url": url, "title": title,
                     "summary": _strip_html(e.get("summary", ""))[:SUMMARY_CHARS] or None,
                     "published_at": _entry_published(e) or None})
    return feed, rows, None


def fetch_feeds() -> dict:
    """전 피드 병렬 수집 → macro_news 멱등 적재. 반환 {ok:[key], failed:[{key, publisher, reason}]}."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_fetch_one, FEEDS))
    ok, failed = [], []
    conn = get_connection()
    try:
        for feed, rows, err in results:
            if rows is None:
                failed.append({"key": feed["key"], "publisher": feed["publisher"], "reason": err})
                continue
            ok.append(feed["key"])
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO macro_news (url, feed, publisher, kind, title, summary, published_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (r["url"], feed["key"], feed["publisher"], feed["kind"],
                     r["title"], r["summary"], r["published_at"]))
        conn.execute("DELETE FROM macro_news WHERE fetched_at < datetime('now', ?)", (f"-{RETAIN_DAYS} days",))
        conn.commit()
    finally:
        conn.close()
    return {"ok": ok, "failed": failed}


def read_window(conn, start_utc: str, end_utc: str) -> list[dict]:
    """[start, end) UTC 구간 헤드라인, 최신순. 같은 제목(여러 섹션 피드 중복)은 하나만."""
    rows = conn.execute(
        "SELECT url, feed, publisher, kind, title, summary, published_at FROM macro_news "
        "WHERE published_at >= ? AND published_at < ? ORDER BY published_at DESC",
        (start_utc, end_utc)).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["title"] in seen:
            continue
        seen.add(r["title"])
        out.append(dict(r))
    return out

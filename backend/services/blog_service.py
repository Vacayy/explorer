import feedparser
from bs4 import BeautifulSoup


def _html_to_summary(html: str, max_chars: int = 200) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()[:max_chars].strip()


def scrape_rss(feed_url: str) -> tuple[list[dict], str]:
    """Fetch posts from any RSS/Atom feed.

    Returns: (posts, blog_name)
    posts: [{title, summary, content, url, published_at}]
    """
    feed = feedparser.parse(feed_url)
    blog_name = feed.feed.get("title", "")
    posts = []
    for entry in feed.entries[:20]:
        content_html = ""
        if entry.get("content"):
            content_html = entry.content[0].get("value", "")
        elif entry.get("summary"):
            content_html = entry.summary

        summary = _html_to_summary(content_html)
        author = entry.get("author", entry.get("dc_creator", ""))
        posts.append({
            "title": entry.get("title", ""),
            "summary": summary,
            "content": content_html,
            "url": entry.get("link", ""),
            "published_at": entry.get("published", entry.get("updated", "")),
            "author": author,
        })
    return posts, blog_name


def fetch_full_content(url: str) -> str | None:
    """Fetch full article content by scraping the actual blog post URL.
    Handles Naver Blog iframe structure and Tistory/generic blogs.
    """
    import requests
    import urllib3
    urllib3.disable_warnings()

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    try:
        resp = requests.get(url, timeout=15, verify=False, headers=headers)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Naver Blog: content is inside an iframe
    if "blog.naver.com" in url:
        iframe = soup.select_one("iframe#mainFrame")
        if iframe and iframe.get("src"):
            iframe_src = iframe["src"]
            if not iframe_src.startswith("http"):
                iframe_src = f"https://blog.naver.com{iframe_src}"
            try:
                resp2 = requests.get(iframe_src, timeout=15, verify=False, headers=headers)
                soup = BeautifulSoup(resp2.text, "html.parser")
            except Exception:
                return None

    # Find content element by platform selectors (most specific first)
    content_el = None
    for selector in [
        ".se-main-container",            # Naver blog (new SmartEditor)
        "#postViewArea",                 # Naver blog (old)
        ".tt_article_useless_p_margin",  # Tistory
        ".area_view",                     # Tistory alt
        ".contents_style",               # Tistory v2
        "#content .entry-content",        # Generic
        ".post-content",                  # Generic
        "article",                        # Semantic HTML
    ]:
        content_el = soup.select_one(selector)
        if content_el and len(content_el.get_text(strip=True)) > 50:
            break
    else:
        content_el = None

    if not content_el:
        return None

    # Clean up scripts, styles
    for tag in content_el.find_all(["script", "style", "noscript"]):
        tag.decompose()

    return str(content_el)


def detect_platform_and_feed_url(blog_url: str) -> tuple[str, str]:
    """Detect platform from blog URL and return (platform, rss_feed_url).

    Supported platforms: tistory, naver (RSS via rss.blog.naver.com), generic
    """
    url = blog_url.strip().rstrip("/")

    if "tistory.com" in url:
        return "tistory", f"{url}/rss"

    if "blog.naver.com" in url:
        blog_id = url.split("blog.naver.com/")[-1].split("/")[0]
        return "naver", f"https://rss.blog.naver.com/{blog_id}.xml"

    # Generic: assume URL is already an RSS feed or we try appending /rss
    # Try to detect if it already looks like an RSS url
    lower = url.lower()
    if any(lower.endswith(ext) for ext in ["/rss", "/feed", ".xml", "/atom"]):
        return "rss", url

    return "rss", f"{url}/rss"


def verify_and_fetch(feed_url: str) -> tuple[list[dict], str]:
    """Verify feed is accessible and return (posts, blog_name).

    Raises ValueError if feed cannot be parsed or has no entries.
    """
    posts, blog_name = scrape_rss(feed_url)
    if not blog_name and not posts:
        raise ValueError("RSS 피드에 접근할 수 없거나 게시글이 없습니다")
    return posts, blog_name

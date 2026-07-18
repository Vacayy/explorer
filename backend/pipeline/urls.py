"""URL 소속 판별 — RSS 직등록 소스(뉴스·뉴스레터)의 문서 귀속.

네이버류 블로그는 '문서 url이 소스 url로 시작' 전제가 성립하지만, RSS 피드를
직접 등록한 소스(rss.hankyung.com ↔ 기사 www.hankyung.com)는 프리픽스가 어긋난다.
→ 소스 url이 피드형(rss/feed 포함)일 때만 도메인 일치로 fallback.
   (프리픽스 전용 유지 이유: blog.naver.com/aaa와 /bbb는 도메인이 같아
   무조건 도메인 매칭하면 오귀속된다)
"""
import re
from urllib.parse import urlparse

_SUB_PREFIX = re.compile(r"^(www|rss|m|feeds?|news)\.")
_FEEDLIKE = re.compile(r"(rss|feed)", re.I)

# 언론사 도메인 — RSS 소스를 '뉴스'(언론사)와 '아티클'(간행물·뉴스레터)로 가르는 기준.
# 새 언론사 RSS를 등록하면 여기 도메인만 추가하면 '뉴스' 탭에 자동 편입된다.
_NEWS_DOMAINS = {
    "mk.co.kr", "hankyung.com", "chosun.com", "biz.chosun.com", "joongang.co.kr",
    "donga.com", "hani.co.kr", "khan.co.kr", "yna.co.kr", "yonhapnews.co.kr",
    "mt.co.kr", "edaily.co.kr", "sedaily.com", "fnnews.com", "mbn.co.kr",
    "asiae.co.kr", "heraldcorp.com", "newsis.com", "wowtv.co.kr", "hankookilbo.com",
    "seoul.co.kr", "kmib.co.kr", "munhwa.com", "hankyung.io",
}


def norm_domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return _SUB_PREFIX.sub("", host)


def is_feedlike(source_url: str) -> bool:
    return bool(_FEEDLIKE.search(source_url or ""))


def is_news_domain(url: str) -> bool:
    return norm_domain(url) in _NEWS_DOMAINS


def blog_category(url: str, platform: str) -> str:
    """blog 소스를 3분류 — 'blog'(개인 블로그) | 'news'(언론사) | 'article'(간행물·뉴스레터)."""
    if platform != "rss":
        return "blog"
    return "news" if is_news_domain(url) else "article"


def url_belongs(doc_url: str, source_url: str) -> bool:
    """문서가 이 소스 소속인가 — 프리픽스 우선, 피드형 소스만 도메인 fallback."""
    if (doc_url or "").startswith(source_url):
        return True
    if not is_feedlike(source_url):
        return False
    d = norm_domain(doc_url)
    return bool(d) and d == norm_domain(source_url)

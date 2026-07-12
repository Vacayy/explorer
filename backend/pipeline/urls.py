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


def norm_domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return _SUB_PREFIX.sub("", host)


def is_feedlike(source_url: str) -> bool:
    return bool(_FEEDLIKE.search(source_url or ""))


def url_belongs(doc_url: str, source_url: str) -> bool:
    """문서가 이 소스 소속인가 — 프리픽스 우선, 피드형 소스만 도메인 fallback."""
    if (doc_url or "").startswith(source_url):
        return True
    if not is_feedlike(source_url):
        return False
    d = norm_domain(doc_url)
    return bool(d) and d == norm_domain(source_url)

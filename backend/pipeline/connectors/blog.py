"""블로그 커넥터 — 기존 services/blog_service 스크레이퍼만 이식.

persistence/tagging 결합은 버리고, 획득 로직만 호출해 RawDoc으로 변환한다.
"""
from pipeline.base import RawDoc, SourceRef
from database import get_connection
from services.blog_service import scrape_rss, detect_platform_and_feed_url


class BlogConnector:
    source_type = "blog"

    def __init__(self, feeds: list[str] | None = None):
        # feeds가 주어지면 그것만, 아니면 활성 blog_sources 전체.
        self._feeds = feeds

    def discover(self) -> list[SourceRef]:
        if self._feeds is not None:
            return [SourceRef(key=u) for u in self._feeds]
        conn = get_connection()
        rows = conn.execute(
            # is_active=개인 노출(뮤트), collect_enabled=수집 자체 (D-126) — 축이 다르다
            "SELECT url FROM blog_sources WHERE COALESCE(collect_enabled,1)=1"
        ).fetchall()
        conn.close()
        return [SourceRef(key=r["url"]) for r in rows]

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        return [self.fetch_post(post) for post in self.discover_posts(ref)]

    def discover_posts(self, ref: SourceRef) -> list[SourceRef]:
        """Capture the RSS listing before fetching individual post bodies."""
        feed_url = ref.key
        try:
            _, detected = detect_platform_and_feed_url(ref.key)
            if detected:
                feed_url = detected
        except Exception:
            pass  # 이미 feed url이거나 감지 실패 → ref.key 그대로 사용

        posts, _blog_name = scrape_rss(feed_url)
        return [SourceRef(key=p.get('url') or p.get('title', ''), meta={'post': p}) for p in posts]

    def fetch_post(self, ref: SourceRef) -> RawDoc:
        p = ref.meta['post']
        body = p.get('content') or p.get('summary', '')
        url = p.get('url')
        is_naver = bool(url) and 'blog.naver.com' in url
        if url and (is_naver or len(body) < 600):
            from services.blog_service import fetch_full_content
            full = fetch_full_content(url)
            if full and len(full) > len(body):
                body = full
        return RawDoc(source_type='blog', source_id=p.get('url') or p.get('title', ''),
                      title=p.get('title', ''), url=p.get('url', ''), published_at=p.get('published_at', ''),
                      raw_content=body, kind='html')

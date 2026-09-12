"""링크 스크랩 커넥터 — 본문 없이 URL만 올리는 채널의 링크를 따라가 원문을 문서로 (D-142).

대상: `telegram_channels.expand_links=1`인 채널(옵트인). 모든 채널의 모든 URL을 따라가면
뉴스 인용 링크까지 긁어와 노이즈가 폭증하므로, 링크 스크랩이 목적인 채널만 켠다.

URL 하나 = 문서 하나(`source_type='scrap'`, `source_id=url`). 한 메시지에 서로 다른 종목
글이 여러 개 들어오므로 메시지에 합치면 엔티티 링크·청킹이 뒤섞인다.

**미검증 소스**: 내가 고르지 않은 개인 주장이라 월드모델·신호·기본 검색에서 제외된다
(pipeline/visibility.UNVERIFIED_SOURCES). 여기는 획득만 하고, 차단은 그 상수를 읽는 쪽이 한다.
"""
import re
import time

import requests
import urllib3

from database import get_connection
from pipeline.base import RawDoc, SourceRef

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

BODY_CAP = 30_000       # 본문 상한 — 12만 자짜리 글이 있어 청크 상한(문서당 80)을 넘지 않게
LOOKBACK_DAYS = 30      # 이 기간의 스크랩 메시지만 스캔
MAX_PER_RUN = 20        # 회차당 링크 수 — 예의(요청 간격)와 실행 시간 상한
MAX_TRIES = 3           # 실패 URL 재시도 상한
FETCH_GAP_SEC = 1.0     # 요청 간격

_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
# 링크 확장 대상이 아닌 것 — 자기 참조·다른 커넥터 담당·파일
_SKIP_HOSTS = ("t.me", "telegram.me", "youtube.com", "youtu.be", "x.com", "twitter.com")
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".xlsx")


def _clean_url(u: str) -> str:
    return u.rstrip(").,'\"")


def _skip(u: str) -> bool:
    low = u.lower()
    return any(h in low for h in _SKIP_HOSTS) or low.endswith(_SKIP_EXT)


def _meta(url: str) -> tuple[str | None, str | None]:
    """페이지 메타에서 제목·작성자. 네이버 블로그는 og:title + naverblog:nickname을 준다."""
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, timeout=15, verify=False, headers=_HEADERS)
        if r.status_code != 200:
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:  # noqa: BLE001 — 네트워크 실패는 제목 없음으로 강등
        return None, None

    def prop(name: str) -> str | None:
        el = soup.select_one(f'meta[property="{name}"]') or soup.select_one(f'meta[name="{name}"]')
        v = (el.get("content") or "").strip() if el else ""
        return v or None

    title = prop("og:title")
    if not title and soup.title:
        title = soup.title.get_text(strip=True) or None
    author = prop("naverblog:nickname") or prop("author") or prop("article:author")
    return title, author


class ScrapConnector:
    source_type = "scrap"

    def __init__(self, channels: list[str] | None = None):
        self._channels = channels

    def discover(self) -> list[SourceRef]:
        if self._channels is not None:
            return [SourceRef(key=c) for c in self._channels]
        conn = get_connection()
        rows = conn.execute(
            "SELECT channel_name FROM telegram_channels "
            "WHERE COALESCE(expand_links,0)=1 AND COALESCE(collect_enabled,1)=1").fetchall()
        conn.close()
        return [SourceRef(key=r["channel_name"]) for r in rows]

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        channel = ref.key
        conn = get_connection()
        try:
            msgs = conn.execute("""
                SELECT id, markdown, published_at FROM raw_documents
                WHERE source_type='telegram' AND source_id LIKE ? || '/%'
                  AND published_at >= datetime('now', ?)
                ORDER BY published_at DESC""", (channel, f"-{LOOKBACK_DAYS} days")).fetchall()

            # URL 대장 갱신 — 처음 본 링크는 등록, 다시 본 링크는 노출 횟수만 올린다
            todo: list[tuple[str, int, str]] = []
            for m in msgs:
                for raw in _URL_RE.findall(m["markdown"] or ""):
                    url = _clean_url(raw)
                    if _skip(url):
                        continue
                    row = conn.execute("SELECT status, tries FROM scrap_links WHERE url=?", (url,)).fetchone()
                    if row is None:
                        # 이미 구독 블로그로 수집된 글이면 스크랩하지 않는다 (중복 방지)
                        dup = conn.execute("SELECT 1 FROM raw_documents WHERE url=? LIMIT 1", (url,)).fetchone()
                        conn.execute(
                            "INSERT INTO scrap_links (url, channel, src_doc_id, status) VALUES (?, ?, ?, ?)",
                            (url, channel, m["id"], "duplicate" if dup else "pending"))
                        if not dup:
                            todo.append((url, m["id"], m["published_at"] or ""))
                    else:
                        conn.execute(
                            "UPDATE scrap_links SET seen_count=seen_count+1, last_seen_at=datetime('now') "
                            "WHERE url=?", (url,))
                        if row["status"] == "failed" and (row["tries"] or 0) < MAX_TRIES:
                            todo.append((url, m["id"], m["published_at"] or ""))
            conn.commit()
        finally:
            conn.close()

        docs: list[RawDoc] = []
        for i, (url, src_doc_id, msg_date) in enumerate(todo[:MAX_PER_RUN]):
            if i:
                time.sleep(FETCH_GAP_SEC)
            doc = self._fetch_one(url, src_doc_id, msg_date, channel)
            if doc:
                docs.append(doc)
        return docs

    def after_store(self, doc: RawDoc, result: dict) -> None:
        """runner 훅 — 적재된 문서 id를 대장에 되쓴다."""
        conn = get_connection()
        try:
            conn.execute("UPDATE scrap_links SET doc_id=? WHERE url=?", (result.get("doc_id"), doc.source_id))
            conn.commit()
        finally:
            conn.close()

    def _fetch_one(self, url: str, src_doc_id: int, msg_date: str, channel: str) -> RawDoc | None:
        from services.blog_service import fetch_full_content
        title, author = _meta(url)
        try:
            body = fetch_full_content(url)
        except Exception:  # noqa: BLE001
            body = None

        conn = get_connection()
        try:
            if not body:
                conn.execute("UPDATE scrap_links SET status='failed', tries=tries+1 WHERE url=?", (url,))
                conn.commit()
                return None
            conn.execute("UPDATE scrap_links SET status='ok', tries=tries+1 WHERE url=?", (url,))
            conn.commit()
        finally:
            conn.close()

        head = f"{title or url}" + (f" · {author}" if author else "")
        # published_at은 글 작성일이 아니라 스크랩된 메시지의 시각 — 원문 발행일 메타가 없다(정직하게 근사).
        return RawDoc(
            source_type="scrap",
            source_id=url,
            title=head[:200],
            url=url,
            published_at=msg_date,
            raw_content=(body or "")[:BODY_CAP],
            kind="html",
        )



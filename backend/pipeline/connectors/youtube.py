"""유튜브 커넥터 — 영상 자막(transcript) 수집.

두 진입점:
- 채널 구독: youtube_channels의 RSS(feeds/videos.xml)에서 신규 영상 → 자막
- 링크 단건: fetch 대상에 video_id 직접 지정 (소스 등록 API가 처리)

자막은 ko 우선 → en → 아무 언어. 자동생성 자막도 허용(없는 것보단 낫다).
추출된 자막은 store→enrich 파이프라인을 그대로 타서 종목·산업 태깅된다.
"""
import re

import feedparser
import requests

from pipeline.base import RawDoc, SourceRef
from database import get_connection

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
_LANG_PREF = ["ko", "en"]
MAX_NEW_PER_CHANNEL = 5   # 채널당 회차 신규 영상 상한 (첫 구독 시 폭주 방지)


def parse_video_id(url_or_id: str) -> str | None:
    s = (url_or_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = re.search(r"(?:v=|/live/|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else None


def resolve_channel_id(url_or_handle: str) -> tuple[str, str] | None:
    """@handle·채널 URL → (channel_id, title). channel/UC… 직접이면 페이지 없이."""
    s = (url_or_handle or "").strip()
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", s)
    if m:
        cid = m.group(1)
        try:
            f = feedparser.parse(requests.get(_RSS.format(cid=cid), headers=_UA, timeout=15).content)
            return cid, f.feed.get("title", cid)
        except Exception:
            return cid, cid
    # @handle 또는 핸들 URL — 페이지에서 canonical channelId 추출
    handle = s
    if "youtube.com" not in s and not s.startswith("@"):
        handle = "@" + s
    page_url = s if "youtube.com" in s else f"https://www.youtube.com/{handle}"
    try:
        html = requests.get(page_url, headers=_UA, timeout=15).text
        m = re.search(r'"(?:channelId|externalId)"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', html)
        if not m:
            m = re.search(r"channel/(UC[A-Za-z0-9_-]{22})", html)
        if m:
            cid = m.group(1)
            tm = re.search(r'"title"\s*:\s*"([^"]{1,80})"', html)
            return cid, (tm.group(1) if tm else cid)
    except Exception:
        pass
    return None


def fetch_transcript(video_id: str) -> str | None:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    try:
        tl = api.list(video_id)
    except Exception:
        return None
    # ko → en → 첫 번째. 수동 자막 우선, 없으면 자동생성.
    codes = {t.language_code: t for t in tl}
    picked = None
    for lang in _LANG_PREF:
        if lang in codes:
            picked = codes[lang]
            break
    if not picked:
        picked = next(iter(tl), None)
    if not picked:
        return None
    try:
        segs = picked.fetch()
    except Exception:
        return None
    text = " ".join(s.text for s in segs if s.text and s.text.strip()).strip()
    return text or None


def _video_title(video_id: str) -> str:
    try:
        r = requests.get(f"https://www.youtube.com/oembed?url=https://youtu.be/{video_id}&format=json",
                         headers=_UA, timeout=10)
        if r.ok:
            return r.json().get("title", "") or video_id
    except Exception:
        pass
    return video_id


def _video_published(video_id: str) -> str:
    """단건 링크는 RSS 메타가 없음 — watch 페이지에서 게시일 추출 (피드 정렬용)."""
    try:
        html = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=_UA, timeout=15).text
        m = re.search(r'"publishDate":"([0-9T:+-]{10,25})', html) or \
            re.search(r'"uploadDate":"([0-9T:+-]{10,25})', html)
        return m.group(1) if m else ""
    except Exception:
        return ""


class YouTubeConnector:
    source_type = "youtube"

    def __init__(self, video_ids: list[str] | None = None):
        # video_ids 지정 시 그것만(링크 단건), 아니면 활성 채널 신규 영상 전체
        self._video_ids = video_ids

    def discover(self) -> list[SourceRef]:
        if self._video_ids is not None:
            return [SourceRef(key=v) for v in self._video_ids]
        conn = get_connection()
        channels = conn.execute(
            "SELECT channel_id, title FROM youtube_channels WHERE is_active=1").fetchall()
        seen = {r["source_id"] for r in conn.execute(
            "SELECT source_id FROM raw_documents WHERE source_type='youtube'")}
        conn.close()
        refs: list[SourceRef] = []
        for ch in channels:
            try:
                f = feedparser.parse(requests.get(
                    _RSS.format(cid=ch["channel_id"]), headers=_UA, timeout=15).content)
            except Exception:
                continue
            new = 0
            for e in f.entries:
                vid = e.get("yt_videoid") or (e.get("id", "").split(":")[-1])
                if not vid or vid in seen:
                    continue
                refs.append(SourceRef(key=vid, meta={
                    "title": e.get("title", ""), "published": e.get("published", ""),
                    "channel": ch["title"]}))
                new += 1
                if new >= MAX_NEW_PER_CHANNEL:
                    break
        return refs

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        vid = parse_video_id(ref.key) or ref.key
        transcript = fetch_transcript(vid)
        if not transcript:
            return []
        title = ref.meta.get("title") or _video_title(vid)
        published = ref.meta.get("published") or _video_published(vid)
        return [RawDoc(
            source_type="youtube",
            source_id=vid,
            title=title,
            url=f"https://www.youtube.com/watch?v={vid}",
            published_at=published,
            raw_content=transcript,
            kind="text",
        )]

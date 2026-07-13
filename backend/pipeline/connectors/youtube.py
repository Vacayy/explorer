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
MAX_TRANSCRIPT_CHARS = 45000  # opus 입력 상한 (긴 라이브 방어)


def digest_transcript(title: str, transcript: str) -> str | None:
    """자막(노이즈·구어체)을 opus로 투자 리서치 정리본(markdown)으로 1차 가공.

    자막 raw는 그 자체로 검색·지식에 노이즈다 — 정리본을 본문으로 삼아
    지식 체계에 흡수한다 (stakeholder 방향, 2026-07-13). 실패 시 None(호출부 fallback).
    """
    import subprocess
    from pipeline.enrich import _claude_bin, llm_engine
    if llm_engine() != "claude-code":
        return None
    prompt = (
        f"유튜브 영상 '{title}'의 자막이다. 음성을 자막화한 것이라 구어체·반복·"
        "인식오류 노이즈가 많다. 이것을 투자 리서치 관점의 정리본(마크다운)으로 재구성해라.\n"
        "구조 (섹션 고정, 마크다운):\n"
        "## 핵심 요약\n화자의 결론과 핵심 메시지. **논지가 바뀔 때마다 문단을 나눠라(빈 줄로 구분)** — "
        "한 덩어리로 쓰지 말 것. 3~4개 문단 권장.\n"
        "## 주요 논점\n**반드시 `- `로 시작하는 불릿 리스트.** 각 항목은 `- **핵심어**: 설명(근거·수치)` 형식.\n"
        "## 언급된 종목·지표·이벤트\n`- **항목**: 값` 불릿 리스트. 종목·수치·일정. 없으면 이 섹션 생략\n"
        "## 투자 시사점\n화자의 포지션·전략과 유효/무효 조건. 2~3개 문단으로 나눠서.\n"
        "규율: 자막에 없는 내용 지어내지 말 것. 인사말·잡담·광고는 버릴 것. "
        "화자의 주관적 주장은 '화자는 ~라고 본다'로 표기해 사실과 구분. 정보 밀도 최대화. "
        "긴 문단은 읽기 쉽게 나눌 것.\n\n"
        f"[자막]\n{transcript[:MAX_TRANSCRIPT_CHARS]}"
    )
    try:
        proc = subprocess.run(
            [_claude_bin(), "-p", "--model", "opus", prompt],
            capture_output=True, text=True, timeout=400)
        if proc.returncode != 0:
            return None
        out = proc.stdout.strip()
        return out if len(out) > 100 else None
    except Exception:
        return None


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
        # 자막 raw 대신 opus 정리본을 본문으로 — 검색·태깅·지식이 정리본을 흡수
        digest = digest_transcript(title, transcript)
        body = f"{digest}\n\n---\n*원본 자막 {len(transcript):,}자 → opus 정리본. 원문: 유튜브 링크*" \
            if digest else transcript
        return [RawDoc(
            source_type="youtube",
            source_id=vid,
            title=title,
            url=f"https://www.youtube.com/watch?v={vid}",
            published_at=published,
            raw_content=body,
            kind="text",
        )]

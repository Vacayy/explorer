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
    # 일시적 실패(호출 blip)로 raw가 영구화되지 않도록 소폭 재시도 — 백오프 5s·10s
    import time
    last = ""
    for attempt in range(3):
        try:
            proc = subprocess.run(
                [_claude_bin(), "-p", "--model", "opus", prompt],
                capture_output=True, text=True, timeout=400)
            if proc.returncode == 0 and len(proc.stdout.strip()) > 100:
                return proc.stdout.strip()
            # claude는 오류(사용량 한도·미로그인 등)를 stdout에 쓴다 — stderr만 보면 원인이 안 보임
            last = (f"rc={proc.returncode} out={proc.stdout.strip()[:160]!r} "
                    f"err={proc.stderr.strip()[:100]!r}")
        except Exception as e:  # noqa: BLE001 — timeout 등도 원인 기록
            last = f"exc={type(e).__name__}:{e}"
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    print(f"[digest_transcript] '{title[:40]}' 3회 실패 — {last}", flush=True)
    return None


def _digest_body(digest: str, transcript: str) -> str:
    """정리본 + 원본 자막 길이 주석 (fetch·백필 공용)."""
    return (f"{digest}\n\n---\n"
            f"*원본 자막 {len(transcript):,}자 → opus 정리본. 원문: 유튜브 링크*")


def parse_video_id(url_or_id: str) -> str | None:
    s = (url_or_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = re.search(r"(?:v=|/live/|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else None


def _channel_title(cid: str) -> str:
    """RSS feed title이 정확한 채널명 — 페이지 파싱은 네비 '홈' 등을 오인함."""
    try:
        f = feedparser.parse(requests.get(_RSS.format(cid=cid), headers=_UA, timeout=15).content)
        return f.feed.get("title", "") or cid
    except Exception:
        return cid


def resolve_channel_id(url_or_handle: str) -> tuple[str, str] | None:
    """@handle·채널 URL → (channel_id, title). title은 항상 RSS 기준."""
    s = (url_or_handle or "").strip()
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", s)
    if m:
        cid = m.group(1)
        return cid, _channel_title(cid)
    # @handle 또는 핸들 URL — 페이지에서 canonical channelId 추출 (title은 RSS로)
    handle = s
    if "youtube.com" not in s and not s.startswith("@"):
        handle = "@" + s
    page_url = s if "youtube.com" in s else f"https://www.youtube.com/{handle}"
    try:
        html = requests.get(page_url, headers=_UA, timeout=15).text
        # canonical 링크 = 이 페이지 '자신'의 채널. externalId = 채널 자체 메타.
        # 주의: 그냥 첫 "channelId"를 잡으면 featured된 서브채널(예: 'Dwarkesh Clips')을
        # 본 채널로 오인한다 — clips 채널 id가 externalId보다 HTML 앞에 나오기 때문.
        m = (re.search(r'<link\s+rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"', html)
             or re.search(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', html)
             or re.search(r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', html))  # 최후 수단
        if m:
            cid = m.group(1)
            return cid, _channel_title(cid)
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


def video_channel_id(video_id: str) -> str | None:
    """영상의 소속 channel_id — 단건 링크도 채널 도시에에 연결되도록."""
    try:
        html = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=_UA, timeout=15).text
        m = re.search(r'"channelId":"(UC[A-Za-z0-9_-]{22})"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def _video_published(video_id: str) -> str:
    """단건 링크는 RSS 메타가 없음 — watch 페이지에서 게시일 추출 (피드 정렬용)."""
    try:
        html = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=_UA, timeout=15).text
        m = re.search(r'"publishDate":"([0-9T:+-]{10,25})', html) or \
            re.search(r'"uploadDate":"([0-9T:+-]{10,25})', html)
        return m.group(1) if m else ""
    except Exception:
        return ""


DIGEST_MARKER = "opus 정리본"


def redigest_youtube(limit: int = 5) -> dict:
    """자막 raw로 굳은 유튜브 문서를 opus 정리본으로 사후 치유 (백필 + 재발 방지).

    수집 당시 opus 실패로 raw 저장된 문서는 커넥터가 다시 안 건드리므로(seen-skip),
    저장분을 직접 스캔해 재요약한다. 성공분만 store_document로 갱신(내용 변경→재enrich).
    실패분은 손대지 않아 다음 회차에 재시도된다. 회차당 상한으로 버스트 실패 방지.
    """
    from pipeline.base import RawDoc
    from pipeline.store import store_document
    conn = get_connection()
    rows = conn.execute(
        "SELECT source_id, title, url, published_at, raw_content FROM raw_documents "
        "WHERE source_type='youtube' AND raw_content NOT LIKE ? "
        "ORDER BY published_at DESC LIMIT ?", (f"%{DIGEST_MARKER}%", limit)).fetchall()
    conn.close()
    digested = failed = 0
    for r in rows:
        transcript = r["raw_content"] or ""
        digest = digest_transcript(r["title"] or "", transcript) if len(transcript) >= 100 else None
        if not digest:
            failed += 1
            continue
        store_document(RawDoc(
            source_type="youtube", source_id=r["source_id"], title=r["title"] or "",
            url=r["url"] or "", published_at=r["published_at"] or "",
            raw_content=_digest_body(digest, transcript), kind="text"))
        digested += 1
    return {"scanned": len(rows), "digested": digested, "failed": failed}


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
        # seen은 video_id 기준 (source_id는 channel/vid 또는 vid 혼재)
        seen = {r["source_id"].split("/")[-1] for r in conn.execute(
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
                    "channel_id": ch["channel_id"], "channel": ch["title"]}))
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
        # 자막 raw 대신 opus 정리본을 본문으로 — 검색·태깅·지식이 정리본을 흡수.
        # 실패 시 raw로 저장되지만, discover()의 seen-skip 때문에 커넥터는 다시 안 건드림 —
        # redigest_youtube 배치가 저장분을 직접 스캔해 사후 치유한다.
        digest = digest_transcript(title, transcript)
        body = _digest_body(digest, transcript) if digest else transcript
        # source_id에 항상 채널 프리픽스 — 단건 링크도 실제 channel_id를 조회해
        # 붙여, 그 채널을 구독하면 도시에(channel/vid LIKE)에 자동 연결된다
        cid = ref.meta.get("channel_id") or video_channel_id(vid)
        source_id = f"{cid}/{vid}" if cid else vid
        return [RawDoc(
            source_type="youtube",
            source_id=source_id,
            title=title,
            url=f"https://www.youtube.com/watch?v={vid}",
            published_at=published,
            raw_content=body,
            kind="text",
        )]

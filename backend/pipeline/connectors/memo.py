"""투자자 메모 커넥터 — 운용사가 공개하는 장문 메모(Oaktree Howard Marks 등).

RSS가 없어 목록 페이지에서 메모 링크를 모으고, 아직 저장하지 않은 것만 받는다(본문은 고쳐지지 않는 발행물).
source_id = '{source}/{slug}' — 피드 리더가 '/' 앞을 채널로 묶는다(timeline._projection).
"""
import html
import re
import urllib.request
from datetime import datetime

from database import get_connection
from pipeline.base import RawDoc, SourceRef

# 새 운용사는 여기 한 줄 — list에서 link 정규식으로 메모 주소를 모은다
SOURCES = {
    "oaktree": {
        "name": "Howard Marks · Oaktree",
        "list": "https://www.oaktreecapital.com/insights/memos",
        "base": "https://www.oaktreecapital.com",
        "link": r'href="(/insights/memo/[a-z0-9-]+)"',
        "skip": {"the-best-of"},   # 모음집 안내 페이지
    },
}
_UA = {"User-Agent": "Mozilla/5.0 (stock-explorer memo reader)"}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_oaktree(page: str) -> tuple[str, str, str] | None:
    """(제목, 발행일 ISO, 본문 HTML). 본문 = h1 다음부터 'Legal Information' 앞. 발행일 = 본문 끝 '<p ...>Month D, YYYY</p>'."""
    m = re.search(r'<h1 class="test-h1">(.*?)</h1>(.*?)<p class="subtitleGreen">\s*Legal Information', page, re.S)
    if not m:
        return None
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    body = m.group(2)
    dates = re.findall(r"<p[^>]*>\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</p>", body)
    if not dates:
        return None
    published = datetime.strptime(dates[-1], "%B %d, %Y").date().isoformat()
    return title, f"{published}T00:00:00+00:00", body


class MemoConnector:
    source_type = "memo"

    def __init__(self, targets: list[str] | None = None):
        # targets: 메모 URL 단건(재수집용). 없으면 목록에서 아직 없는 것만
        self._targets = targets

    def discover(self) -> list[SourceRef]:
        if self._targets:
            return [SourceRef(key=u, meta={"source": next((k for k, s in SOURCES.items() if u.startswith(s["base"])), "oaktree")})
                    for u in self._targets]
        conn = get_connection()
        try:
            have = {r[0] for r in conn.execute("SELECT source_id FROM raw_documents WHERE source_type='memo'")}
        finally:
            conn.close()
        refs = []
        for key, src in SOURCES.items():
            slugs = dict.fromkeys(re.findall(src["link"], _get(src["list"])))   # 순서 유지 중복 제거
            for path in slugs:
                slug = path.rsplit("/", 1)[-1]
                if slug in src["skip"] or f"{key}/{slug}" in have:
                    continue
                refs.append(SourceRef(key=src["base"] + path, meta={"source": key}))
        return refs

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        key = ref.meta.get("source", "oaktree")
        parsed = parse_oaktree(_get(ref.key))
        if not parsed:
            return []
        title, published, body = parsed
        return [RawDoc(source_type="memo", source_id=f"{key}/{ref.key.rstrip('/').rsplit('/', 1)[-1]}",
                       title=title, url=ref.key, published_at=published, raw_content=body, kind="html")]

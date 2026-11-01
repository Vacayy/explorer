"""정규화: RawDoc → markdown 텍스트.

- text/html: 블로그·텔레그램은 기존 스크레이퍼가 이미 텍스트/HTML을 추출하므로
  html은 가볍게 태그 제거만. (결정 #3: 블로그는 기존 텍스트 추출 유지)
  줄은 블록 요소 경계에서만 바꾼다 — 모든 텍스트 노드 사이에 줄을 넣으면 굵게·링크에서 문장이 끊기고
  네이버 본문이 빈 줄 투성이가 된다. <img>는 이미지 해석 줄로 바뀐다 (docs/specs/image-reading.md).
- pdf: markitdown으로 변환 (첨부/향후 컨콜 전용). markitdown 미설치 시 graceful degrade.
"""
from pipeline.base import RawDoc

_BLOCK = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote",
          "section", "article", "figure", "figcaption", "pre", "hr", "dl", "dt", "dd", "header", "footer"]


def _collapse(text: str) -> str:
    """줄 앞뒤 공백 제거 + 연속 빈 줄을 하나로."""
    out: list[str] = []
    for line in (l.strip() for l in text.split("\n")):
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _html_to_text(html: str, doc: RawDoc | None = None) -> str:
    from bs4 import BeautifulSoup
    from pipeline import image_reading
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    refs: list[tuple[str, str]] = []
    for img in soup.find_all("img"):
        ref = image_reading.blog_image_ref(img) if doc is not None else None
        if ref and len(refs) < image_reading.MAX_PER_DOC:
            img.replace_with(f"\n{image_reading.placeholder(len(refs))}\n")
            refs.append(ref)
        else:
            img.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.insert_after(" ")
    for el in soup.find_all(_BLOCK):
        el.insert_before("\n")
        el.insert_after("\n")
    text = _collapse(soup.get_text().replace("​", "").replace("\xa0", " "))
    if refs:
        text = _collapse(image_reading.fill_placeholders(
            text, refs, title=doc.title, published_at=doc.published_at,
            source="블로그·뉴스 글", page_url=doc.url))
    return text


def _pdf_to_markdown(path: str) -> str:
    try:
        from markitdown import MarkItDown
    except Exception:
        return ""  # markitdown 미설치 → 빈 문자열 (파이프라인은 계속)
    try:
        return MarkItDown().convert(path).text_content
    except Exception:
        return ""


def to_markdown(doc: RawDoc) -> str:
    if doc.markdown is not None:
        return doc.markdown
    if doc.kind == "html":
        return _html_to_text(doc.raw_content, doc)
    if doc.kind == "pdf":
        return _pdf_to_markdown(doc.raw_content)
    return doc.raw_content or ""

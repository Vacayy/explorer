"""정규화: RawDoc → markdown 텍스트.

- text/html: 블로그·텔레그램은 기존 스크레이퍼가 이미 텍스트/HTML을 추출하므로
  html은 가볍게 태그 제거만. (결정 #3: 블로그는 기존 텍스트 추출 유지)
- pdf: markitdown으로 변환 (첨부/향후 컨콜 전용). markitdown 미설치 시 graceful degrade.
"""
from pipeline.base import RawDoc


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(html or "", "html.parser").get_text("\n").strip()


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
    if doc.kind == "html":
        return _html_to_text(doc.raw_content)
    if doc.kind == "pdf":
        return _pdf_to_markdown(doc.raw_content)
    return doc.raw_content or ""

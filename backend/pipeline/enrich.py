"""문서 강화(enrich).

ANTHROPIC_API_KEY가 있으면 LLM으로 요약·감성·엔티티 추출, 없으면 키워드 fallback.
반환: {summary, sentiment, model, industries[], topics[], _text}
(엔티티 링크 해석은 store._link에서 수행)
"""
import os

from services.tagging_service import INDUSTRY_KEYWORDS, TOPIC_KEYWORDS


def enrich(title: str, markdown: str) -> dict:
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _enrich_llm(title, markdown)
        except Exception as e:  # 키는 있으나 anthropic 미설치/오류 → fallback
            print(f"[enrich] LLM 실패, 키워드 fallback: {e}")
    return _enrich_keyword(title, markdown)


def _enrich_keyword(title: str, markdown: str) -> dict:
    text_upper = f"{title} {markdown}".upper()
    industries = [
        tag for tag, kws in INDUSTRY_KEYWORDS.items()
        if any(kw.upper() in text_upper for kw in kws)
    ]
    topics = [
        tag for tag, kws in TOPIC_KEYWORDS.items()
        if any(kw.upper() in text_upper for kw in kws)
    ]
    summary = (markdown or "").strip().replace("\n", " ")[:200]
    return {
        "summary": summary,
        "sentiment": None,
        "model": "keyword",
        "industries": industries,
        "topics": topics,
    }


def _enrich_llm(title: str, markdown: str) -> dict:
    """LLM enrich. ANTHROPIC_API_KEY 확보 후 활성화.

    Haiku로 태깅/엔티티, Sonnet로 요약. 구조화 출력(JSON schema) 강제.
    현재는 미구현 → ImportError로 키워드 fallback 유도.
    """
    raise ImportError("LLM enrich 미구현 (ANTHROPIC_API_KEY 확보 후 활성화)")

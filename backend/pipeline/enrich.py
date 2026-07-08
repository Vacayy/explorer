"""문서 강화(enrich).

엔진 선택 (opt-in — cron이 몰래 quota/비용을 쓰지 않도록 env로 명시):
  ENRICH_ENGINE=claude-code  → claude -p --model haiku (Claude Code 구독, API 키 불필요)
  ANTHROPIC_API_KEY 존재     → Anthropic API (Haiku — 태깅은 가성비 티어)
  둘 다 없음                 → 키워드 fallback

반환: {summary, sentiment, model, industries[], topics[], stocks[]?}
- stocks는 LLM이 별칭·약칭('하이닉스'→'SK하이닉스')을 정식 종목명으로 정규화한 결과.
  존재하면 store._link가 substring 매칭 대신 이것을 confidence 0.9로 사용한다.
"""
import json
import os
import shutil
import subprocess

from services.tagging_service import INDUSTRY_KEYWORDS, TOPIC_KEYWORDS

HAIKU_API_MODEL = "claude-haiku-4-5-20251001"
MAX_DOC_CHARS = 4000  # 토큰 통제 — 태깅에는 앞부분이면 충분


def _claude_bin() -> str | None:
    return os.getenv("CLAUDE_BIN") or shutil.which("claude")


def llm_engine() -> str | None:
    if os.getenv("ENRICH_ENGINE", "").strip().lower() == "claude-code" and _claude_bin():
        return "claude-code"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "api"
    return None


def llm_available() -> bool:
    return llm_engine() is not None


def enrich(title: str, markdown: str) -> dict:
    if llm_available():
        try:
            return _enrich_llm(title, markdown)
        except Exception as e:
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


def _build_prompt(title: str, markdown: str) -> str:
    doc = f"{title}\n{(markdown or '')[:MAX_DOC_CHARS]}"
    return (
        "다음 한국 투자 관련 문서를 분석해 JSON만 출력해. 설명·코드블록 금지.\n"
        '형식: {"stocks": [{"name": "정식 종목명"}], "industries": [], "topics": [], '
        '"summary": "핵심 2문장", "sentiment": "positive|neutral|negative"}\n'
        "규칙:\n"
        "- stocks: 실제로 논의 대상인 한국 상장사만. 별칭·약칭(하이닉스=SK하이닉스, 삼전=삼성전자 등)은 "
        "반드시 정식 종목명으로 정규화. 스쳐 지나가는 언급은 제외.\n"
        f"- industries: 다음 목록에서만 선택: {', '.join(INDUSTRY_KEYWORDS)}\n"
        f"- topics: 다음 목록 우선 사용: {', '.join(TOPIC_KEYWORDS)}. 꼭 필요하면 2단어 이내로 신규 허용.\n"
        f"문서:\n{doc}"
    )


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"JSON 없음: {text[:80]}")
    return json.loads(text[start:end + 1])


def _call_claude_code(prompt: str) -> str:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "haiku", "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    envelope = json.loads(proc.stdout)
    return envelope.get("result", "")


def _call_api(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=HAIKU_API_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def _enrich_llm(title: str, markdown: str) -> dict:
    engine = llm_engine()
    prompt = _build_prompt(title, markdown)
    raw = _call_claude_code(prompt) if engine == "claude-code" else _call_api(prompt)
    data = _parse_json(raw)
    stocks = data.get("stocks") or []
    return {
        "summary": data.get("summary"),
        "sentiment": data.get("sentiment"),
        "model": f"{engine}/haiku",
        "industries": data.get("industries") or [],
        "topics": data.get("topics") or [],
        "stocks": [s.get("name") for s in stocks if isinstance(s, dict) and s.get("name")],
    }

"""RAG 질의응답 — 하이브리드 검색 + claude-code 종합 (docs/specs/phase2-rag.md).

규율:
- 출처 인용 필수 — 제공된 문서 근거 없이 답하지 않는다 (인용 없는 주장은 갭으로 표시).
- 갭 분석을 일급 출력으로 (gbrain 패턴): 근거 부족 / 문서 간 모순 / 오래된 정보.
- 답변은 epistemic상 '가설'이다 — UI는 가설 스타일로 표시한다.
- 모델: 종합은 sonnet (티어 분리 원칙 — 태깅=haiku, 종합=sonnet). RAG_MODEL로 변경 가능.
"""
import json
import os
import subprocess

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine
from pipeline.search import search

RAG_MODEL = os.getenv("RAG_MODEL", "sonnet")
TOP_K = 8
EXCERPT_CHARS = 1200


def _fetch_docs(doc_ids: list[int]) -> list[dict]:
    if not doc_ids:
        return []
    conn = get_connection()
    ph = ",".join("?" for _ in doc_ids)
    rows = {r["id"]: r for r in conn.execute(f"""
        SELECT id, source_type, title, url, published_at, substr(markdown, 1, {EXCERPT_CHARS}) excerpt
        FROM raw_documents WHERE id IN ({ph})""", doc_ids)}
    conn.close()
    return [dict(rows[d]) for d in doc_ids if d in rows]  # 검색 랭킹 순 유지


def _history_block(history: list[dict] | None) -> str:
    """스레드 후속질문용 이전 문답 — 최근 6개, 답변은 400자 절단 (토큰 규약)."""
    if not history:
        return ""
    lines = []
    for m in history[-6:]:
        tag = "사용자" if m.get("role") == "user" else "이전 답변"
        lines.append(f"{tag}: {(m.get('content') or '')[:400]}")
    return "\n\n[이전 대화 — 후속질문의 맥락. 근거는 여전히 아래 문서만]\n" + "\n".join(lines)


def _build_prompt(question: str, docs: list[dict], history: list[dict] | None = None) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] ({d['source_type']}, {(d['published_at'] or '')[:10]}) {d['title']}\n{d['excerpt']}"
        for i, d in enumerate(docs)
    )
    return (
        "너는 개인 투자 리서치 어시스턴트다. 아래 수집 문서들만 근거로 질문에 답해라.\n"
        "JSON만 출력 (설명·코드블록 금지):\n"
        '{"answer": "마크다운 답변 — 모든 주장 뒤에 [번호] 인용", '
        '"citations": [실제로 인용한 문서 번호들], '
        '"gaps": [{"type": "unsupported|contradiction|stale|missing", "note": "한 줄"}]}\n'
        "규칙:\n"
        "- 문서에 근거가 없는 내용은 답변에 넣지 말고, 알 수 없다면 그렇게 말해라\n"
        "- 갭 분석: 근거가 약한 부분(unsupported), 문서끼리 상충(contradiction), "
        "문서가 오래돼 최신 상황과 다를 수 있음(stale), 질문에 답하기에 빠진 정보(missing)\n"
        "- note 소스는 사용자의 자체 가설 메모다 — 사실과 구분해서 다뤄라\n"
        f"- 오늘 날짜 기준으로 문서 날짜의 신선도를 판단해라\n\n"
        f"{_history_block(history)}\n\n질문: {question}\n\n수집 문서:\n{ctx}"
    )


def ask(question: str, history: list[dict] | None = None) -> dict:
    if llm_engine() != "claude-code" and not os.getenv("ANTHROPIC_API_KEY"):
        return {"error": "LLM 엔진 없음 (ENRICH_ENGINE=claude-code 또는 ANTHROPIC_API_KEY 필요)"}

    # 후속질문("그럼 마이크론은?")은 단독으로 검색이 안 됨 — 직전 사용자 질문을 검색어에 포함
    search_q = question
    if history:
        prev_user = [m["content"] for m in history if m.get("role") == "user"]
        if prev_user:
            search_q = f"{prev_user[-1]} {question}"

    hits = search(search_q, k=TOP_K)
    docs = _fetch_docs([h["doc_id"] for h in hits])
    if not docs:
        return {"answer": None, "citations": [], "gaps": [
            {"type": "missing", "note": "질문과 관련된 수집 문서가 없습니다."}], "model": None}

    prompt = _build_prompt(question, docs, history)
    if llm_engine() == "claude-code":
        proc = subprocess.run(
            [_claude_bin(), "-p", "--model", RAG_MODEL, "--output-format", "json", prompt],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
        raw = json.loads(proc.stdout).get("result", "")
        model = f"claude-code/{RAG_MODEL}"
    else:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model="claude-sonnet-5", max_tokens=2048,
            messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in msg.content if b.type == "text")
        model = "api/sonnet"

    s, e = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[s:e + 1])

    cited_idx = [i for i in (data.get("citations") or []) if isinstance(i, int) and 1 <= i <= len(docs)]
    return {
        "answer": data.get("answer"),
        "citations": [{
            "n": i,
            "doc_id": docs[i - 1]["id"],
            "title": docs[i - 1]["title"],
            "url": docs[i - 1]["url"],
            "source_type": docs[i - 1]["source_type"],
            "published_at": docs[i - 1]["published_at"],
        } for i in cited_idx],
        "gaps": data.get("gaps") or [],
        "model": model,
    }

"""미국 사업부 매출 수집 — EX-99.1 earnings release에서 LLM(haiku) 추출 (ia-redesign §4.13 '분기 손익 흐름').

왜 LLM인가: SEC XBRL companyfacts JSON은 dimension(`StatementBusinessSegmentsAxis`)을 돌려주지 않아
자동 수집이 불가하다. raw XBRL instance 파싱은 회사별 분류 축 구조가 제각각이라 유지 비용이 크다.
반면 EX-99.1 요약 표는 거의 모든 회사가 '세그먼트 이름 | 분기 매출' 모양으로 통일해 둔다(스캐니아 수준 아님).
분기당 티커당 ~1회 호출로 세그먼트 표 하나만 꺼낸다 — $0.0002/회 수준.

흐름:
1. `us_quarterly`에 있는 티커의 가장 최근 N건 EX-99.1(`raw_documents.source_type='earnings_release'`,
   `source_id` 앞에 티커, `EX-99.1` 서픽스)을 대상.
2. LLM(task='segments.extract')로 {period, segments: [{name, revenue}]} JSON.
3. 성공한 것만 `us_segments`에 upsert. 실패는 로그만, 다음 수집 때 재시도.
"""
from __future__ import annotations

import json
import re
from datetime import date

from database import get_connection
from pipeline import llm
from pipeline.us_fundamentals import _quarter_key


SYSTEM_PROMPT = """이 문서는 미국 상장사의 분기 실적 보도자료(EX-99.1)다. 회사가 밝힌 **이번 분기** 사업부 매출만 추출하라.

규칙:
- '사업부(segment)'는 회사가 Revenue by segment, Market Platform, Reportable Segment 같은 이름으로 표에 명시한 분류다.
  Geographic breakdown(지역별), Product line 같은 세부 분류는 쓰지 않는다. **세그먼트 보고(segment reporting)로 공시한 묶음만.**
- 금액은 **백만 달러 단위 숫자**(예: 89,000) — 공시가 '$89.0 billion'이면 89000, '$89.0B'이면 89000.
- 세그먼트 이름은 공시 표기 그대로(영문·대소문자 유지). Compute & Networking, Graphics, Data Center 등.
- 이번 분기 끝나는 날짜(period_end)를 YYYY-MM-DD로.
- 세그먼트 표를 못 찾거나 애매하면 segments: [].

반환 JSON만:
{"period_end": "YYYY-MM-DD" | null,
 "segments": [{"name": "...", "revenue_m": number}, ...]}"""


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["period_end", "segments"],
    "properties": {
        "period_end": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "revenue_m"],
                "properties": {
                    "name": {"type": "string"},
                    "revenue_m": {"type": "number"},
                },
            },
        },
    },
}


def _parse_llm_json(payload: str) -> dict | None:
    for m in re.finditer(r"\{.*\}", payload, re.DOTALL):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def extract_one(doc_id: int, ticker: str, markdown: str) -> dict:
    """문서 하나에서 세그먼트 추출·저장. 세그먼트가 0개여도 안 실패로 취급."""
    # 앞 ~6KB면 거의 모든 earnings release의 요약 표를 커버
    prompt = f"티커: {ticker}\n\n보도자료:\n\n{markdown[:8000]}\n\n세그먼트 매출을 JSON으로."
    try:
        result = llm.run(prompt, task="segments.extract", system=SYSTEM_PROMPT, json_schema=SCHEMA)
    except Exception as e:  # noqa: BLE001
        return {"status": "llm_error", "doc_id": doc_id, "error": type(e).__name__}
    parsed = _parse_llm_json(result.text)
    if not parsed:
        return {"status": "parse_failed", "doc_id": doc_id}
    period_end = parsed.get("period_end")
    segments = parsed.get("segments") or []
    if not period_end:
        return {"status": "no_period", "doc_id": doc_id, "segments": len(segments)}
    q = _quarter_key(period_end)
    if not segments:
        return {"status": "no_segments", "doc_id": doc_id, "q": q}
    conn = get_connection()
    try:
        # 재추출이면 같은 분기 세그먼트는 통째로 교체(이름 바뀌는 경우 대응)
        conn.execute("DELETE FROM us_segments WHERE ticker=? AND q=?", (ticker, q))
        for s in segments:
            conn.execute(
                "INSERT INTO us_segments (ticker, q, segment_name, revenue, source_doc_id, fetched_at) "
                "VALUES (?,?,?,?,?, datetime('now'))",
                (ticker, q, s["name"], float(s["revenue_m"]) * 1e6, doc_id),
            )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "doc_id": doc_id, "q": q, "segments": len(segments)}


def _pending_releases(conn, tickers: list[str], per_ticker: int) -> list[tuple[int, str, str]]:
    """각 티커의 최근 EX-99.1 중 아직 세그먼트가 추출 안 된 것(ticker, q 모두 등록 안 된 것)."""
    out: list[tuple[int, str, str]] = []
    for ticker in tickers:
        rows = conn.execute(
            "SELECT id, source_id, markdown FROM raw_documents "
            "WHERE source_type='earnings_release' AND source_id LIKE ? AND source_id LIKE '%EX-99.1' "
            "ORDER BY published_at DESC LIMIT ?",
            (f"{ticker}:%", per_ticker),
        ).fetchall()
        for r in rows:
            # 이미 추출됐으면 건너뜀(소스 문서 id 기준)
            exists = conn.execute(
                "SELECT 1 FROM us_segments WHERE source_doc_id=? LIMIT 1", (r["id"],)).fetchone()
            if exists:
                continue
            out.append((r["id"], ticker, r["markdown"] or ""))
    return out


def collect(tickers: list[str] | None = None, per_ticker: int = 4, limit: int | None = 40) -> dict:
    """us_quarterly 티커(또는 지정)의 최근 per_ticker건 EX-99.1에서 세그먼트 추출. 한 번에 limit건."""
    conn = get_connection()
    try:
        if tickers is None:
            tickers = [r["ticker"] for r in conn.execute(
                "SELECT DISTINCT ticker FROM us_quarterly ORDER BY ticker").fetchall()]
        pending = _pending_releases(conn, tickers, per_ticker)
    finally:
        conn.close()
    if limit is not None:
        pending = pending[:limit]
    stored, failed, empty = 0, 0, 0
    first_errors: list[str] = []
    for doc_id, ticker, md in pending:
        r = extract_one(doc_id, ticker, md)
        if r.get("status") == "ok":
            stored += r.get("segments", 0)
        elif r.get("status") == "no_segments":
            empty += 1
        else:
            failed += 1
            if len(first_errors) < 3:
                first_errors.append(f"{ticker}#{doc_id}: {r.get('status')}")
    return {"attempted": len(pending), "stored_rows": stored, "no_segments": empty,
            "failed": failed, "errors": first_errors,
            "status": "ok" if stored else ("error" if not pending else "partial")}

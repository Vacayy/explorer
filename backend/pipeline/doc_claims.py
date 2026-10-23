"""문서 상세 '논점별 관련 자료' (docs/specs/doc-related-claims.md, D-233).

자료마다 이어 읽을 만한 논점 1~3개를 haiku로 한 번 뽑고(상세를 처음 열 때, 결과 저장), 논점마다
대화 검색과 같은 청크 하이브리드 검색 + 리랭커(`rag.retrieve_docs`)로 그 논점을 다루는 대목이 있는 자료를 찾는다.
- 리랭커 점수 MIN_RERANK 미만은 붙이지 않는다 — 맞는 자료가 없는 논점은 숨긴다(칸을 억지로 채우지 않음).
- 인용 한 줄은 LLM이 쓴 문장이 아니라 찾은 대목의 원문 문장(리랭커로 고름) — 자료가 말한 것과 해석의 구분.
- 리랭커가 없으면 기준을 적용할 수 없어 실패로 남긴다(조용한 degrade 금지).
"""
from __future__ import annotations

import json
import re
import time
import uuid

from database import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_claims (
    doc_id        INTEGER PRIMARY KEY,
    content_hash  TEXT,                 -- 만들 때의 원문 해시 — 원문이 바뀌면 다시 만든다
    status        TEXT NOT NULL,        -- running | ok | failed | skipped
    token         TEXT,
    payload       TEXT,                 -- {"claims":[{"claim","query_ko","query_en","related":[{"id","quote","score"}]}]}
    error         TEXT,
    model         TEXT,
    updated_at    REAL
);
"""
MIN_CHARS = 600          # 이보다 짧은 자료(텔레그램 단문)는 논점 없이 유사도 목록만
INPUT_CHARS = 12_000
MAX_CLAIMS = 3
PER_CLAIM = 2
MIN_RERANK = -1.0        # 2026-10-14 문서 5개×2회 실측: -1.0~-1.2 구간은 엉뚱한 자료가 더 많았다(-1.2에서 올림)
STALE_SECONDS = 600
MODEL = "haiku"

PROMPT = """아래 자료에서 독자가 이어서 더 읽어 보고 싶어질 핵심 논점을 1~3개 뽑아라(짧은 자료면 1개).
- claim: 이 자료가 내세우는 주장·해석을 한국어 평서문 한 문장으로("~다", 40자 이하).
  · 자료 요약이 아니라 다른 회사·산업·자료로 이어 읽을 수 있는 주장.
    좋음: "관세 환급금은 일회성 이익으로 가격 인하에 재투자된다" / 나쁨: "코스트코는 FY2027에 창고 33곳을 연다"(이 자료의 사실 요약)
  · 대상(산업·현상·정책)이 드러나게. 금지: 어디에나 해당하는 일반론("정책은 세부 설계가 중요하다"), 자료 속 일화·인물 소개.
- query_ko: 그 논점을 다른 자료에서 찾을 한국어 검색 문장(핵심어 포함, 40자 이내).
- query_en: 같은 내용의 영어 검색 문장(영어 자료·컨콜용).
JSON만 출력: {{"claims":[{{"claim":"...","query_ko":"...","query_en":"..."}}]}}

제목: {title}
본문:
{body}"""

_BOILERPLATE = re.compile(r"(As Senior Analyst|All rights reserved|Copyright|subscrib|notified|newsletter|뉴스레터|"
                          r"무단 ?전재|재배포 ?금지|구독|기자 ?=|https?://|@\w)", re.I)


class RerankUnavailable(RuntimeError):
    pass


def _sentences(text: str) -> list[str]:
    from pipeline.image_reading import strip_ai_notes
    parts = re.split(r"(?<=[.!?。])\s+|\n+", strip_ai_notes(text))   # 원문 인용 — AI 이미지 해석 줄은 후보가 아니다
    return [s.strip(" -•·\t") for s in parts
            if 25 <= len(s.strip()) <= 220 and not _BOILERPLATE.search(s) and s.count("|") + s.count("●") < 2]   # 표 행·글머리 나열은 문장이 아니다


def pick_quote(claim: str, text: str) -> str | None:
    """찾은 대목에서 논점과 가장 맞닿은 원문 문장 하나. 저자 소개·저작권 문구 같은 상투 문장은 뺀다."""
    from pipeline.rerank import rerank
    sents = _sentences(text)[:40]
    if not sents:
        return None
    scores = rerank(claim, sents)
    if not scores:
        return sents[0]
    return sents[max(range(len(sents)), key=lambda i: scores[i])]


def _parse(text: str) -> list[dict]:
    from pipeline.llm import extract_json
    data = extract_json(text or "") or {}
    out = []
    for c in data.get("claims") or []:
        claim, ko, en = (str(c.get(k) or "").strip() for k in ("claim", "query_ko", "query_en"))
        if claim and ko:
            out.append({"claim": claim, "query_ko": ko, "query_en": en})
    return out[:MAX_CLAIMS]


def _same_event(doc_id: int) -> set[int]:
    """같은 회사의 같은 실적 발표(컨콜↔보도자료, ±3일) — 이어 읽을 '다른' 자료가 아니라 같은 사건이다.
    회사·날짜는 엔티티 링크(삼성전자 같은 언급 오탐)·게시 시각(Fool 게시가 늦음)이 아니라 수집 시 기록한 티커·발표일로."""
    conn = get_connection()
    try:
        return {r[0] for r in conn.execute("""
            WITH ev AS (SELECT raw_doc_id AS doc_id, ticker, call_date AS d FROM transcripts
                        UNION SELECT doc_id, ticker, filing_date FROM earnings_releases)
            SELECT oe.doc_id FROM ev me JOIN ev oe ON oe.ticker = me.ticker
            WHERE me.doc_id = ? AND abs(julianday(substr(oe.d, 1, 10)) - julianday(substr(me.d, 1, 10))) <= 3""",
            (doc_id,))}
    finally:
        conn.close()


def find_related(doc_id: int, claims: list[dict]) -> list[dict]:
    """논점별 관련 자료 — 자기 자신·같은 실적 발표·앞 논점에 이미 붙은 자료는 제외, 리랭커 기준 미달은 버린다."""
    from pipeline.rag import retrieve_docs
    used, out, quotes = {doc_id} | _same_event(doc_id), [], set()
    for c in claims:
        hits = retrieve_docs(c["query_ko"], k=8, variants=[v for v in (c["query_en"], c["claim"]) if v])
        if hits and all(h.get("rerank_score") is None for h in hits):
            raise RerankUnavailable("리랭커를 쓸 수 없어 관련도 기준을 적용하지 못했습니다")
        related = []
        for h in hits:
            if h["id"] in used or (h.get("rerank_score") or -99) < MIN_RERANK:
                continue
            quote = pick_quote(c["claim"], (h.get("excerpt") or "").split("\n", 1)[-1])
            if quote and quote in quotes:      # 같은 글의 재게시·A/S가 같은 문장을 되풀이
                continue
            quotes.add(quote)
            related.append({"id": h["id"], "quote": quote, "score": h["rerank_score"]})
            used.add(h["id"])
            if len(related) >= PER_CLAIM:
                break
        if related:
            out.append({**c, "related": related})
    return out


def compute(doc_id: int) -> dict:
    from pipeline import llm
    conn = get_connection()
    try:
        r = conn.execute("SELECT title, markdown, raw_content FROM raw_documents WHERE id=?", (doc_id,)).fetchone()
    finally:
        conn.close()
    from pipeline.image_reading import strip_ai_notes
    body = strip_ai_notes(r["markdown"] or r["raw_content"] or "")[:INPUT_CHARS]   # 자료의 논점 — AI 이미지 해석은 저자의 말이 아니다
    res = llm.run(PROMPT.format(title=r["title"] or "", body=body), model=MODEL, job="doc_claims", timeout=180)
    claims = _parse(res.text)
    if not claims:
        raise ValueError("논점을 뽑지 못했습니다")
    return {"claims": find_related(doc_id, claims)}


def _row(conn, doc_id: int):
    return conn.execute("""SELECT c.*, rd.content_hash AS doc_hash, length(coalesce(rd.markdown, rd.raw_content, '')) AS n
        FROM raw_documents rd LEFT JOIN doc_claims c ON c.doc_id = rd.id WHERE rd.id=?""", (doc_id,)).fetchone()


def state(doc_id: int) -> dict | None:
    """{status: none|running|ok|failed|skipped, error, claims[관련 자료 메타 포함]}. 문서가 없으면 None."""
    from pipeline.sources import source_names
    conn = get_connection()
    try:
        r = _row(conn, doc_id)
        if not r:
            return None
        status = r["status"]
        if status is None or (status in ("ok", "skipped") and r["content_hash"] != r["doc_hash"]):
            status = "none"
        elif status == "running" and time.time() - (r["updated_at"] or 0) > STALE_SECONDS:
            status = "failed"
        claims = json.loads(r["payload"])["claims"] if status == "ok" and r["payload"] else []
        ids = [x["id"] for c in claims for x in c["related"]]
        meta = {}
        if ids:
            rows = conn.execute(f"SELECT id, source_type, source_id, url, title, published_at FROM raw_documents "
                                f"WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
            ch = source_names(conn, rows)
            meta = {m["id"]: {"source_type": m["source_type"], "title": m["title"], "published_at": m["published_at"],
                              "channel": (ch.get(m["id"]) or {}).get("name")} for m in rows}
        claims = [{"claim": c["claim"], "related": [{**x, **meta[x["id"]]} for x in c["related"] if x["id"] in meta]}
                  for c in claims]
        error = r["error"] if status == "failed" else None
        if status == "failed" and not error:
            error = "논점 정리가 중단되었습니다. 다시 시도해 주세요."
        return {"status": status, "error": error, "claims": [c for c in claims if c["related"]]}
    finally:
        conn.close()


def queue(doc_id: int) -> dict:
    """{status, token}. token이 있으면 호출부가 execute를 백그라운드로 돌린다."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = _row(conn, doc_id)
        if not r:
            return {"status": "missing", "token": None}
        fresh = r["content_hash"] == r["doc_hash"]
        if r["status"] in ("ok", "skipped") and fresh:
            return {"status": r["status"], "token": None}
        if r["status"] == "running" and time.time() - (r["updated_at"] or 0) <= STALE_SECONDS:
            return {"status": "running", "token": None}
        short = (r["n"] or 0) < MIN_CHARS
        token = None if short else uuid.uuid4().hex
        conn.execute("""INSERT INTO doc_claims (doc_id, content_hash, status, token, payload, error, model, updated_at)
            VALUES (?,?,?,?,NULL,NULL,?,?) ON CONFLICT(doc_id) DO UPDATE SET content_hash=excluded.content_hash,
            status=excluded.status, token=excluded.token, payload=NULL, error=NULL, model=excluded.model,
            updated_at=excluded.updated_at""",
                     (doc_id, r["doc_hash"], "skipped" if short else "running", token, MODEL, time.time()))
        conn.commit()
        return {"status": "skipped" if short else "running", "token": token}
    finally:
        conn.close()


def execute(doc_id: int, token: str) -> None:
    payload, error = None, None
    try:
        payload = compute(doc_id)
    except RerankUnavailable as e:
        error = f"{e}. 관리자에게 검색 인덱스 작업(build_search_index) 상태를 확인해 달라고 해 주세요."
    except Exception as e:  # noqa: BLE001 — 사유를 남기고 화면에서 다시 시도할 수 있게
        error = f"논점을 정리하지 못했습니다({type(e).__name__}). Claude 인증·사용량을 확인한 뒤 다시 시도해 주세요."
    from pipeline.ops import retry_locked

    def _save():
        conn = get_connection()
        try:
            conn.execute("UPDATE doc_claims SET status=?, payload=?, error=?, updated_at=? WHERE doc_id=? AND token=?",
                         ("ok" if payload else "failed", json.dumps(payload, ensure_ascii=False) if payload else None,
                          error, time.time(), doc_id, token))
            conn.commit()
        finally:
            conn.close()
    retry_locked(_save)

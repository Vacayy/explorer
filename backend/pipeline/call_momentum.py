"""실적 발언 모멘텀 — 컨콜·실적 보도자료에서 직전 분기 대비 새로 생기거나 빨라진 성장 동인 (docs/specs/transcript-momentum.md, D-217).

  추출 — 문서(보도자료·CFO 코멘터리·컨콜)마다 haiku 1회. 같은 회사 직전 실적 발표의 동인 이름을 함께 줘 new/accelerating을 판단하게 한다.
         인용문은 원문에 실제로 있는지 서버가 확인하고, 확인 안 된 항목은 점수에 넣지 않는다(지어낸 근거 차단).
  판정 — 결정적. 실적 발표(보도자료 공시일 기준, 컨콜은 ±며칠 안이면 같은 발표로 묶음)별로 출처를 합쳐 직전 발표와 비교.
  알림 — 주 1회 텔레그램, 지난 7일 새로 후보가 된 것.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS call_extracts (
    doc_id      INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    source      TEXT NOT NULL,           -- release | commentary | transcript
    payload     TEXT,                    -- 추출 JSON(인용 검증 후)
    error       TEXT,
    model       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_call_extracts_ticker ON call_extracts(ticker, event_date);
CREATE TABLE IF NOT EXISTS call_momentum (
    ticker      TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    score       REAL NOT NULL,
    status      TEXT NOT NULL,           -- candidate | none | first
    reasons     TEXT NOT NULL,           -- JSON: drivers·guidance·tone·sources
    first_candidate_at TEXT,             -- 처음 후보가 된 시각(주간 알림 기준)
    computed_at TEXT DEFAULT (datetime('now')),
    summary     TEXT,                    -- AI 핵심 요약(이번 시즌 후보만, sonnet) — 근거가 바뀌면 다시 쓴다
    summary_hash TEXT,                   -- 요약에 쓴 근거의 해시
    PRIMARY KEY (ticker, event_date)
);
"""
STATUS_RANK = {"new": 3, "accelerating": 2, "steady": 1, "decelerating": 0}
CANDIDATE_SCORE = 7          # 5점이면 비교 가능한 발표의 ~37%가 후보였다(2026-10-12 37건 실측) — 추리는 기준이 아니었다
_STOP = {"the", "and", "for", "with", "growth", "revenue", "demand", "segment", "business", "market", "new", "strong", "data"}
# 점수에 넣는 가이던스는 성장 지표만 — 세율·비용 가이던스는 '하향'이 호재라 방향이 거꾸로다(NVDA FY27 세율 하향이 감점된 사례)
GROWTH_METRIC = re.compile(r"revenue|sales|bookings|backlog|orders|shipments|arr\b|growth|demand|units|subscribers", re.I)
TRANSCRIPT_WINDOW = (-3, 14)     # 보도자료 공시일 기준 컨콜 날짜 허용 범위(일)
HEAD, TAIL = 26_000, 14_000      # 긴 컨콜은 앞(발표)과 뒤(Q&A)만

PROMPT = """너는 셀사이드 애널리스트다. 아래는 {company}({ticker})의 {kind}다. 성장 모멘텀 관점에서 사실만 구조화하라.

[직전 실적 발표에서 이미 언급된 성장 동인]
{prior}

규칙:
- drivers: 매출·수요를 끌어올리는 구체적 동인(제품·고객·사업부·시장·가격·캐파). 상태는
  new(위 목록에 없고 이번에 처음 등장한 제품·고객·계약·시장·사업) / accelerating(있던 동인인데 이번에 성장 표현이 강해짐) /
  steady / decelerating 중 하나. 직전 목록이 '(없음)'이면 new를 쓰지 말고 steady·accelerating·decelerating만.
  매출·예약·이용자·마진 같은 '지표' 이름은 new가 될 수 없다 — 지표는 그것을 움직인 동인으로 바꿔 쓰거나 accelerating/steady로.
  위 목록의 동인을 다른 말로 부른 것이면 같은 동인이다(new 아님).
- guidance: 회사가 낸 전망. 방향은 raised / lowered / maintained / initiated.
- demand_tone: 수요·수주잔고·가시성 표현의 강도 1(약함)~5(매우 강함).
- qa_focus: 애널리스트가 반복해 물은 주제(컨콜이 아니면 빈 배열).
- quote는 반드시 원문에 그대로 있는 영어 문장 일부(20~200자)를 복사한다. 지어내지 마라.
JSON만 출력:
{{"drivers":[{{"name":"짧은 영문 명사구","type":"product|customer|segment|market|pricing|capacity","status":"new|accelerating|steady|decelerating","magnitude":"규모 표현(있으면)","quote":"..."}}],
 "guidance":[{{"metric":"...","direction":"raised|lowered|maintained|initiated","quote":"..."}}],
 "demand_tone":3,"qa_focus":["..."]}}

[원문]
{text}"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%$.]+", " ", (s or "").lower()).strip()


def verify(payload: dict, text: str) -> dict:
    """인용문이 원문에 있는 항목만 verified=True. 원문 대조는 소문자·구두점 정규화 후 앞 80자."""
    body = _norm(text)
    for key in ("drivers", "guidance"):
        for item in payload.get(key) or []:
            q = _norm(item.get("quote", ""))[:80]
            item["verified"] = len(q) >= 15 and q in body
    return payload


def _source_of(doc: sqlite3.Row) -> str:
    if doc["source_type"] == "transcript":
        return "transcript"
    return "commentary" if "코멘터리" in (doc["title"] or "") else "release"


def events(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    """실적 발표 목록(오래된 순): 보도자료 공시일 기준, 창 안의 컨콜은 같은 발표로."""
    rel = conn.execute("SELECT er.doc_id, er.filing_date, rd.source_type, rd.title FROM earnings_releases er "
                       "JOIN raw_documents rd ON rd.id=er.doc_id WHERE er.ticker=? ORDER BY er.filing_date", (ticker,)).fetchall()
    canon = canonical_dates(conn, ticker, [r["filing_date"] for r in rel])
    by: dict[str, list] = {}
    for r in rel:
        by.setdefault(canon[r["filing_date"]], []).append(r)
    dates = sorted(by)
    for t in conn.execute("SELECT t.raw_doc_id doc_id, t.call_date, rd.source_type, rd.title FROM transcripts t "
                          "JOIN raw_documents rd ON rd.id=t.raw_doc_id WHERE t.ticker=? AND t.call_date IS NOT NULL", (ticker,)):
        cd = date.fromisoformat(t["call_date"][:10])
        near = [d for d in dates if TRANSCRIPT_WINDOW[0] <= (cd - date.fromisoformat(d)).days <= TRANSCRIPT_WINDOW[1]]
        key = near[-1] if near else t["call_date"][:10]
        by.setdefault(key, []).append(t)
    return [{"date": d, "docs": by[d]} for d in sorted(by)]


def canonical_dates(conn: sqlite3.Connection, ticker: str, dates: list[str]) -> dict[str, str]:
    """같은 회계분기의 Item 2.02 공시는 마지막(본 실적) 날짜 하나로 — TSLA 인도량·SMCI 잠정 실적이 별도 '실적 발표'로
    잡혀 직전 분기와 비교되던 것을 막는다. 결산 월을 모르면 날짜 그대로."""
    from pipeline.transcript import fiscal_label
    row = conn.execute("SELECT fiscal_year_end FROM transcript_follow WHERE ticker=?", (ticker,)).fetchone()
    fye = row[0] if row else None
    if not fye:
        return {d: d for d in dates}
    last: dict[tuple[int, int], str] = {}
    for d in dates:
        k = fiscal_label(d, fye)
        last[k] = max(last.get(k, d), d)
    return {d: last[fiscal_label(d, fye)] for d in dates}


def remap_event_dates(conn: sqlite3.Connection) -> int:
    """기존 추출의 event_date를 현재 묶음 규칙에 맞춘다(묶음이 바뀌면 판정 전에)."""
    n = 0
    for (ticker,) in conn.execute("SELECT DISTINCT ticker FROM call_extracts").fetchall():
        for ev in events(conn, ticker):
            for d in ev["docs"]:
                n += conn.execute("UPDATE call_extracts SET event_date=? WHERE doc_id=? AND event_date!=?", (ev["date"], d["doc_id"], ev["date"])).rowcount
    conn.commit()
    return n


def prior_drivers(conn: sqlite3.Connection, ticker: str, before: str) -> list[str]:
    prev = conn.execute("SELECT max(event_date) d FROM call_extracts WHERE ticker=? AND event_date < ? AND payload IS NOT NULL",
                        (ticker, before)).fetchone()["d"]
    if not prev:
        return []
    names = []
    for r in conn.execute("SELECT payload FROM call_extracts WHERE ticker=? AND event_date=? AND payload IS NOT NULL", (ticker, prev)):
        names += [d.get("name", "") for d in json.loads(r["payload"]).get("drivers", []) if d.get("name")]
    return sorted(set(names))


def _commit(conn: sqlite3.Connection, tries: int = 6) -> None:
    """다른 작업(30분 체인·다른 세션)이 오래 쓰면 busy_timeout(30s)을 넘겨 'database is locked'가 난다 — 기다렸다 다시."""
    import time
    for k in range(tries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or k == tries - 1:
                raise
            time.sleep(10 * (k + 1))


def extract_pending(conn: sqlite3.Connection, limit: int = 40, call=None, only: list[str] | None = None) -> dict:
    """아직 추출 안 한 문서를 이번 시즌 회사 먼저, 회사 안에서는 오래된 발표부터(직전 동인 목록이 먼저 있어야 new 판단이 된다)."""
    if call is None:
        from pipeline.enrich import _call_claude_code, llm_available
        if not llm_available():
            return {"extracted": 0, "reason": "llm 미가용"}

        def call(prompt):
            return _call_claude_code(prompt, model="haiku", timeout=180)
    done = {r[0] for r in conn.execute("SELECT doc_id FROM call_extracts")}
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM transcript_follow WHERE active=1 ORDER BY ticker")]
    if only:
        tickers = [t for t in tickers if t in only]
    from pipeline.transcript import FRESH_DAYS
    # 이번 시즌(최근 14일 SEC 실적 발표) 회사 먼저 — 하루 한도를 지난 분기 백필이 먼저 써 버리지 않게(2026-10-22)
    recent = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM earnings_releases WHERE filing_date >= date('now', ?)",
                                         (f"-{FRESH_DAYS} days",))}
    tickers.sort(key=lambda t: t not in recent)
    stats = {"extracted": 0, "failed": 0}
    for ticker in tickers:
        name = (conn.execute("SELECT company_name FROM transcript_follow WHERE ticker=?", (ticker,)).fetchone() or [ticker])[0]
        for ev in events(conn, ticker):
            for d in ev["docs"]:
                if d["doc_id"] in done:
                    continue
                if stats["extracted"] + stats["failed"] >= limit:
                    return stats
                md = conn.execute("SELECT markdown FROM raw_documents WHERE id=?", (d["doc_id"],)).fetchone()["markdown"] or ""
                text = md if len(md) <= HEAD + TAIL else md[:HEAD] + "\n...\n" + md[-TAIL:]
                src = _source_of(d)
                kind = {"release": "실적 보도자료", "commentary": "CFO 코멘터리", "transcript": "실적 컨퍼런스콜 녹취"}[src]
                prior = prior_drivers(conn, ticker, ev["date"])
                try:
                    raw = call(PROMPT.format(company=name, ticker=ticker, kind=kind, prior="\n".join(f"- {p}" for p in prior) or "(없음)", text=text))
                    payload = verify(json.loads(raw[raw.find("{"):raw.rfind("}") + 1]), md)
                    conn.execute("INSERT OR REPLACE INTO call_extracts (doc_id, ticker, event_date, source, payload, model) VALUES (?,?,?,?,?, 'haiku')",
                                 (d["doc_id"], ticker, ev["date"], src, json.dumps(payload, ensure_ascii=False)))
                    stats["extracted"] += 1
                except Exception as e:  # noqa: BLE001 — 실패는 기록해 두고 다음 실행에서 다시 시도하지 않는다(무한 재시도 방지)
                    conn.execute("INSERT OR REPLACE INTO call_extracts (doc_id, ticker, event_date, source, error) VALUES (?,?,?,?,?)",
                                 (d["doc_id"], ticker, ev["date"], src, f"{type(e).__name__}: {str(e)[:200]}"))
                    stats["failed"] += 1
                _commit(conn)
                done.add(d["doc_id"])
    return stats


def _tokens(name: str) -> set[str]:
    return {w for w in _norm(name).split() if len(w) >= 4 and w not in _STOP}


def downgrade_renamed(drivers: list[dict], prior_names: list[str]) -> list[dict]:
    """'new'인데 직전 동인과 핵심 단어가 겹치면 같은 것을 다르게 부른 것으로 보고 accelerating으로(이름 흔들림 — ABNB 사례)."""
    prior = [_tokens(n) for n in prior_names]
    out = []
    for d in drivers:
        if d.get("status") == "new" and any(_tokens(d.get("name", "")) & p for p in prior):
            d = {**d, "status": "accelerating", "renamed": True}
        out.append(d)
    return out


def mentioned_before(drivers: list[dict], prior_text: str) -> list[dict]:
    """'new'인데 핵심 단어의 절반 이상이 직전 실적 발표 원문에 이미 있으면 새것이 아니다 → accelerating.
    LLM은 직전 '동인 목록'에 없으면 new로 넉넉히 붙인다(2026-10-12 실측: new 194개 중 152개가 직전 원문에 이미 있었음 — AAPL 'Greater China')."""
    body = _norm(prior_text)
    out = []
    for d in drivers:
        toks = _tokens(d.get("name", ""))
        if d.get("status") == "new" and body and toks and sum(t in body for t in toks) / len(toks) >= 0.5:
            d = {**d, "status": "accelerating", "seen_before": True}
        out.append(d)
    return out


def _event_text(conn: sqlite3.Connection, ticker: str, event_date: str) -> str:
    return " ".join(r[0] or "" for r in conn.execute(
        "SELECT rd.markdown FROM call_extracts ce JOIN raw_documents rd ON rd.id=ce.doc_id WHERE ce.ticker=? AND ce.event_date=?",
        (ticker, event_date)))


def _combine(rows: list[sqlite3.Row]) -> dict:
    drivers: dict[str, dict] = {}
    guidance, tones, sources, focus = [], [], set(), []
    for r in rows:
        p = json.loads(r["payload"])
        sources.add(r["source"])
        for d in p.get("drivers") or []:
            if not d.get("verified"):
                continue
            k = _norm(d.get("name", ""))
            if k and (k not in drivers or STATUS_RANK.get(d.get("status"), 1) > STATUS_RANK.get(drivers[k]["status"], 1)):
                drivers[k] = {**d, "source": r["source"]}
        guidance += [{**g, "source": r["source"]} for g in p.get("guidance") or [] if g.get("verified")]
        if isinstance(p.get("demand_tone"), (int, float)):
            tones.append(p["demand_tone"])
        focus += p.get("qa_focus") or []
    return {"drivers": list(drivers.values()), "guidance": guidance, "tone": max(tones) if tones else None,
            "sources": sorted(sources), "qa_focus": focus[:6]}


def score(cur: dict, prev: dict | None, history: list[tuple[float, str]] | None = None) -> tuple[float, str]:
    """새 동인 +3(최대 3)·가속 +1(최대 3, LLM이 넉넉히 붙여 약하게)·가이던스 상향 +2(최대 2)·수요 어조 상승 +1·둔화 −2.
    분기 가이던스는 매번 새로 내 'initiated'가 기본이라 점수에 넣지 않는다(2026-10-12 NVDA 5분기 실측: 매 분기 후보·점수 19~36).
    후보 = 5점 이상 + 성장 동인이 있고, 최근 두 발표에 후보가 없었거나 마지막 후보보다 3점 이상 높을 때 — '새로' 맞은 모멘텀만.
    (직전 한 번만 보면 계속 강한 회사가 격분기로 다시 올라온다 — NVDA 실측)"""
    if prev is None:
        return 0.0, "first"
    st = [d.get("status") for d in cur["drivers"]]
    s = 3 * min(st.count("new"), 3) + min(st.count("accelerating"), 3) - 2 * st.count("decelerating")
    growth_guides = [g for g in cur["guidance"] if GROWTH_METRIC.search(g.get("metric") or "")]
    s += 2 * min(sum(g.get("direction") == "raised" for g in growth_guides), 2) - 2 * sum(g.get("direction") == "lowered" for g in growth_guides)
    if cur["tone"] is not None and prev.get("tone") is not None and cur["tone"] - prev["tone"] >= 1:
        s += 1
    growth = "new" in st or "accelerating" in st
    recent = [sc for sc, stt in (history or [])[-2:] if stt == "candidate"]
    fresh = not recent or s >= recent[-1] + 3
    return float(s), "candidate" if s >= CANDIDATE_SCORE and growth and fresh else "none"


def judge(conn: sqlite3.Connection, tickers: list[str] | None = None) -> dict:
    """발표별 점수 갱신. 새로 후보가 되면 first_candidate_at을 찍고 signals(call_momentum)에 적재."""
    tickers = tickers or [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM call_extracts")]
    new_candidates = 0
    for ticker in tickers:
        evs = [r["event_date"] for r in conn.execute(
            "SELECT DISTINCT event_date FROM call_extracts WHERE ticker=? AND payload IS NOT NULL ORDER BY event_date", (ticker,))]
        prev, prev_ev, history = None, None, []
        for ev in evs:
            cur = _combine(conn.execute("SELECT source, payload FROM call_extracts WHERE ticker=? AND event_date=? AND payload IS NOT NULL",
                                        (ticker, ev)).fetchall())
            if prev:
                cur["drivers"] = mentioned_before(cur["drivers"], _event_text(conn, ticker, prev_ev))
                cur["drivers"] = downgrade_renamed(cur["drivers"], [d.get("name", "") for d in prev["drivers"]])
            s, status = score(cur, prev, history)
            old = conn.execute("SELECT status, first_candidate_at FROM call_momentum WHERE ticker=? AND event_date=?", (ticker, ev)).fetchone()
            first_at = old["first_candidate_at"] if old and old["first_candidate_at"] else None
            if status == "candidate" and not first_at:
                first_at = conn.execute("SELECT datetime('now')").fetchone()[0]
                new_candidates += 1
                ent = conn.execute("SELECT entity_id FROM transcript_follow WHERE ticker=?", (ticker,)).fetchone()
                if ent and ent["entity_id"]:
                    conn.execute("INSERT INTO signals (signal_type, entity_id, date, payload_json) VALUES ('call_momentum', ?, ?, ?) "
                                 "ON CONFLICT(signal_type, entity_id, date) DO UPDATE SET payload_json=excluded.payload_json",
                                 (ent["entity_id"], ev, json.dumps({"ticker": ticker, "score": s, **cur}, ensure_ascii=False)))
            # 요약 칼럼은 그대로 둔다(INSERT OR REPLACE면 매일 판정 때 요약이 지워진다)
            conn.execute("INSERT INTO call_momentum (ticker, event_date, score, status, reasons, first_candidate_at) VALUES (?,?,?,?,?,?) "
                         "ON CONFLICT(ticker, event_date) DO UPDATE SET score=excluded.score, status=excluded.status, reasons=excluded.reasons, "
                         "first_candidate_at=excluded.first_candidate_at, computed_at=datetime('now')",
                         (ticker, ev, s, status, json.dumps({**cur, "prev_tone": prev.get("tone") if prev else None}, ensure_ascii=False), first_at))
            prev, prev_ev = cur, ev
            history.append((s, status))
    conn.commit()
    return {"tickers": len(tickers), "new_candidates": new_candidates}


SUMMARY_PROMPT = """너는 셀사이드 애널리스트다. 아래는 {company}({ticker})의 {date} 실적 발표에서 뽑은 성장 모멘텀 근거다(원문 인용 확인됨).
한국어로 핵심을 요약하라.
규칙:
- 2~3문장, 280자 이내. 첫 문장은 결론부터: 이번 발표에서 무엇이 새로 나오거나 빨라졌나.
- 숫자는 아래 근거에 있는 것만 쓴다. 근거에 없는 사실·전망·주가·투자 판단은 쓰지 않는다.
- 제품·고객 이름은 영어 원문 그대로 써도 된다.
- 성장 지표 가이던스 상향·하향이 있으면 한 번 언급한다. 애널리스트 질문 초점은 있으면 마지막에 짧게.
요약문만 출력한다(머리말·불릿·따옴표 없이).

[근거]
{facts}"""
_STATUS_KO = {"new": "새 동인", "accelerating": "가속", "steady": "유지", "decelerating": "둔화"}
_GUIDE_KO = {"raised": "상향", "lowered": "하향", "maintained": "유지", "initiated": "제시"}


def summary_facts(reasons: dict) -> str:
    """요약 입력 — 카드에 보이는 것과 같은 근거(성장 동인·바뀐 가이던스·수요 어조·질문 초점)."""
    lines = [f"- [{_STATUS_KO.get(d.get('status'), d.get('status'))}] {d.get('name')}"
             + (f" ({d['magnitude']})" if d.get("magnitude") else "") + f": \"{d.get('quote', '')}\""
             for d in reasons.get("drivers") or [] if d.get("status") in ("new", "accelerating", "decelerating")]
    lines += [f"- 가이던스 {_GUIDE_KO.get(g.get('direction'), g.get('direction'))} · {g.get('metric')}: \"{g.get('quote', '')}\""
              for g in reasons.get("guidance") or [] if g.get("direction") in ("raised", "lowered")]
    if reasons.get("tone") is not None:
        lines.append(f"- 수요 어조(1~5): 직전 {reasons.get('prev_tone', '-')} → 이번 {reasons['tone']}")
    if reasons.get("qa_focus"):
        lines.append(f"- 애널리스트 질문 초점: {', '.join(reasons['qa_focus'])}")
    return "\n".join(lines)


def summarize(conn: sqlite3.Connection, call=None, limit: int = 30, today: date | None = None) -> dict:
    """이번 시즌 후보 카드의 AI 핵심 요약 — 근거 해시가 바뀐 것만(하루 판정마다 다시 쓰지 않는다). 실패는 다음 실행에서 다시."""
    import hashlib
    if call is None:
        from pipeline.enrich import _call_claude_code, llm_available
        if not llm_available():
            return {"summarized": 0, "reason": "llm 미가용"}

        def call(prompt):
            return _call_claude_code(prompt, model="sonnet", timeout=180)
    start = season((today or date.today()).isoformat())["start"]
    rows = conn.execute("SELECT cm.ticker, cm.event_date, cm.reasons, cm.summary_hash, tf.company_name FROM call_momentum cm "
                        "LEFT JOIN transcript_follow tf ON tf.ticker=cm.ticker WHERE cm.status='candidate' AND cm.event_date >= ? "
                        "ORDER BY cm.event_date DESC", (start,)).fetchall()
    stats = {"summarized": 0, "failed": 0, "unchanged": 0}
    for r in rows:
        facts = summary_facts(json.loads(r["reasons"]))
        h = hashlib.sha1(facts.encode()).hexdigest()[:16]
        if h == r["summary_hash"]:
            stats["unchanged"] += 1
            continue
        if stats["summarized"] + stats["failed"] >= limit:
            break
        try:
            text = call(SUMMARY_PROMPT.format(company=r["company_name"] or r["ticker"], ticker=r["ticker"], date=r["event_date"], facts=facts)).strip()
            if not text:
                raise ValueError("빈 응답")
            conn.execute("UPDATE call_momentum SET summary=?, summary_hash=? WHERE ticker=? AND event_date=?", (text, h, r["ticker"], r["event_date"]))
            _commit(conn)
            stats["summarized"] += 1
        except Exception as e:  # noqa: BLE001 — 요약이 없어도 카드는 근거로 보인다
            print(f"[cm_summary] {r['ticker']} {r['event_date']} 실패: {type(e).__name__}: {e}")
            stats["failed"] += 1
    return stats


def season(day: str) -> dict:
    """발표일 → 실적 시즌. 분기가 끝난 다음 날부터 그 분기의 시즌(10~12월 발표 = 3분기 시즌).
    회계연도가 달력과 다른 회사(NVDA 8월 발표 등)도 발표 시점으로 같은 시즌에 묶는다 — 사용자가 시장을 보는 단위."""
    d = date.fromisoformat(day[:10])
    q = (d.month - 1) // 3          # 0..3: 발표가 난 분기
    year, reported = (d.year - 1, 4) if q == 0 else (d.year, q)
    start = date(d.year, q * 3 + 1, 1)
    return {"key": f"{year}Q{reported}", "label": f"{year}년 {reported}분기 실적 시즌", "start": start.isoformat()}


def by_season(conn: sqlite3.Connection, today: date | None = None, history_days: int = 400) -> dict:
    """전면은 이번 시즌 후보만, 지난 시즌은 기록으로 묶는다(2026-10-13 사용자: 3분기 시즌에 2분기 신호가 전면에 나오지 않게)."""
    today = today or date.today()
    cur = season(today.isoformat())
    items = candidates(conn, (today - date.fromisoformat(cur["start"])).days + history_days)
    current = [c for c in items if c["event_date"] >= cur["start"]]
    history: dict[str, dict] = {}
    for c in items:
        if c["event_date"] < cur["start"]:
            s = season(c["event_date"])
            history.setdefault(s["key"], {**s, "candidates": []})["candidates"].append(c)
    reported = conn.execute("SELECT count(DISTINCT ticker) FROM call_momentum WHERE event_date >= ?", (cur["start"],)).fetchone()[0]
    return {"season": {**cur, "reported": reported}, "candidates": current,
            "history": sorted(history.values(), key=lambda h: h["key"], reverse=True)}


def candidates(conn: sqlite3.Connection, days: int = 120) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for r in conn.execute("SELECT cm.*, tf.company_name FROM call_momentum cm LEFT JOIN transcript_follow tf ON tf.ticker=cm.ticker "
                          "WHERE cm.status='candidate' AND cm.event_date >= ? ORDER BY cm.event_date DESC, cm.score DESC", (since,)):
        reasons = json.loads(r["reasons"])
        out.append({"ticker": r["ticker"], "name": r["company_name"], "event_date": r["event_date"], "score": r["score"],
                    "first_candidate_at": r["first_candidate_at"], "summary": r["summary"], **reasons})
    return out


def coverage(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {"universe": q("SELECT count(*) FROM transcript_follow WHERE active=1"),
            "with_releases": q("SELECT count(DISTINCT ticker) FROM earnings_releases"),
            "with_transcripts": q("SELECT count(DISTINCT ticker) FROM transcripts"),
            "extracted_docs": q("SELECT count(*) FROM call_extracts WHERE payload IS NOT NULL"),
            "failed_docs": q("SELECT count(*) FROM call_extracts WHERE error IS NOT NULL"),
            "comparable": q("SELECT count(*) FROM (SELECT ticker FROM call_momentum GROUP BY ticker HAVING sum(status!='first') > 0)")}


def weekly_message(conn: sqlite3.Connection, top: int = 5) -> tuple[list[tuple[str, str]], str]:
    """지난 7일 새로 후보가 된 발표 중 실적 발표가 최근 21일 안인 것 상위 N — (발송 키, 줄) 목록."""
    rows = conn.execute("SELECT cm.*, tf.company_name FROM call_momentum cm LEFT JOIN transcript_follow tf ON tf.ticker=cm.ticker "
                        "WHERE cm.status='candidate' AND cm.first_candidate_at >= datetime('now','-7 day') "
                        "AND cm.event_date >= date('now','-21 day') ORDER BY cm.score DESC LIMIT ?",   # 백필로 판정된 옛 발표는 알리지 않는다
                        (top,)).fetchall()
    items = []
    for r in rows:
        rs = json.loads(r["reasons"])
        drv = [d for d in rs["drivers"] if d.get("status") in ("new", "accelerating")][:2]
        g = [x for x in rs["guidance"] if x.get("direction") == "raised"][:1]
        e = html.escape   # LLM 추출·외부 회사명 — 텔레그램 HTML에 그대로 넣지 않는다
        parts = [f"{'🆕' if d['status'] == 'new' else '⏫'} {e(d['name'])}" + (f" ({e(d['magnitude'])})" if d.get("magnitude") else "") for d in drv]
        parts += [f"가이던스 상향: {e(x['metric'])}" for x in g]
        items.append((f"callmom:{r['ticker']}:{r['event_date']}",
                      f"· <b>{e(r['company_name'] or r['ticker'])}</b>({e(r['ticker'])}) {r['event_date'][5:]} 점수 {r['score']:.0f} — " + " · ".join(parts)))
    return items, "📈 <b>이번 주 실적 발언 새 모멘텀</b>"

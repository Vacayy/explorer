"""피드 증권사 전망 추출 (docs/specs/value-chain.md §15 3단계) — 피드 문서의 증권사·리서치·회사 가이던스 전망을 전망 원장으로.

비용 원칙(반복 LLM 작업):
- 대상 고르기는 결정적(LLM 0): 전망 어휘 + 기관 이름 + 밸류체인 낱말이 함께 있는 문서만
- 한 문서는 한 번만(exp_feed_docs), 회당 상한(일간 25 · 백필 100), 관리자 스위치(run_job 플래그 'exp_feed')
- 추출은 haiku + 구조화 출력(json_schema). 형식 맞추기라 저렴한 모델로 충분하다
환각 방지: 모델이 낸 원문 인용(quote)이 실제 문서에 없으면 버리고 n_dropped로 센다.
저장: expectation_claims(source='feed', source_org=기관, doc_id, url=문서 URL 또는 'doc:<id>').
"""
from __future__ import annotations

import json
import re

MODEL = "haiku"
CAP = {False: 25, True: 100}
DAYS = {False: 3, True: 60}
DOC_CHARS = 6000

FORECAST = ["전망", "예상", "추정", "상향", "하향", "목표주가", "가이던스", "컨센서스", "forecast", "expect", "estimate", "guidance", "outlook", "project"]
ORGS = ["골드만", "Goldman", "모건스탠리", "Morgan Stanley", "JP모건", "JPMorgan", "J.P. Morgan", "씨티", "Citi", "BofA", "뱅크오브아메리카",
        "UBS", "번스타인", "Bernstein", "제프리스", "Jefferies", "맥쿼리", "Macquarie", "노무라", "Nomura", "바클레이즈", "Barclays",
        "도이치", "Deutsche", "웰스파고", "Wells Fargo", "에버코어", "Evercore", "멜리우스", "Melius", "TrendForce", "트렌드포스",
        "SemiAnalysis", "세미애널리시스", "Counterpoint", "카운터포인트", "IDC", "Gartner", "가트너", "Omdia", "옴디아", "Yole",
        "증권", "리서치센터"]
CHIP = ["HBM", "DRAM", "D램", "디램", "NAND", "낸드", "반도체", "파운드리", "foundry", "AI 서버", "AI server", "GPU", "가속기", "CoWoS",
        "패키징", "기판", "MLCC", "CCL", "PCB", "광모듈", "트랜시버", "데이터센터", "data center", "capex", "설비투자", "웨이퍼", "장비"]

# 기관 이름 통일(문서마다 영문·한글이 섞인다) — 같은 전망을 한 줄로 묶는 기준
ORG_ALIASES = {"goldman sachs": "골드만삭스", "goldman": "골드만삭스", "morgan stanley": "모건스탠리", "jpmorgan": "JP모건",
               "j.p. morgan": "JP모건", "jp morgan": "JP모건", "citi": "씨티", "citigroup": "씨티", "bank of america": "BofA",
               "bofa securities": "BofA", "bernstein": "번스타인", "jefferies": "제프리스", "macquarie": "맥쿼리", "nomura": "노무라",
               "barclays": "바클레이즈", "deutsche bank": "도이치뱅크", "wells fargo": "웰스파고", "evercore": "에버코어", "evercore isi": "에버코어",
               "melius": "멜리우스", "trendforce": "TrendForce", "트렌드포스": "TrendForce", "counterpoint": "카운터포인트", "gartner": "가트너",
               "omdia": "옴디아", "semianalysis": "SemiAnalysis", "세미애널리시스": "SemiAnalysis"}


def norm_org(org: str) -> str:
    o = (org or "").strip()
    return ORG_ALIASES.get(o.lower(), o)


METRICS = ["price_qoq", "price_yoy", "shipments_yoy", "shipments_qoq", "revenue_yoy", "revenue_qoq", "capex_yoy", "market_yoy",
           "demand_yoy", "supply_yoy", "growth_yoy", "eps_yoy", "target_price", "tam"]

SYSTEM = """너는 증권 리서치 문서에서 '시장 기대(전망)'만 뽑는 추출기다. 사실(이미 일어난 실적)은 뽑지 않는다.
규칙:
- 뽑는 것: 특정 기관·애널리스트·회사가 낸 앞으로의 전망·추정·가이던스·목표치(가격·출하·매출·설비투자·시장 규모 성장률 등)
- 뽑지 않는 것: 이미 발표된 실적, 기관이 없는 기자 의견, 조건부 가정('만약 …라면'), 숫자가 없는 전망
- source_org: 전망을 낸 기관명(예: 골드만삭스, TrendForce, SK하이닉스 가이던스). 문서에 명시된 것만.
  증권사·투자은행·리서치 기관·시장조사 기관·회사(공식 가이던스)·국제기구만 된다. 팟캐스트·유튜버·개인 투자자·예측시장(폴리마켓 등)·기자 의견은 뽑지 않는다
- 지표가 metric 목록 어디에도 맞지 않으면 그 전망은 뽑지 않는다('other' 금지 — 투자 회수 기간·파산 확률 같은 것)
- node_key: 주어진 밸류체인 칸 목록(이름·설명)에서 가장 맞는 칸 key, 맞는 칸이 없으면 "".
  예: 서버·AI 서버 시장 → ai_odm, 하이퍼스케일러·클라우드 설비투자 → ai, D램·HBM·낸드 → memory, GPU·AI 가속기 → ai_accel
- 값: 백분율 변화면 unit '%', 범위는 value_low~value_high, 하락은 음수. 금액·규모면 unit을 'USD bn' 등으로
- target_period: 2026Q4 · 2026H2 · 2027 형식, 모르면 ""
- quote: 근거 문장을 문서에서 그대로 복사(200자 이내, 바꿔 쓰지 말 것)
- 전망이 없으면 claims를 빈 배열로"""


def node_catalog() -> list[tuple[str, str]]:
    """(key, '이름 — 설명') — 설명이 있어야 '서버 시장'을 AI 서버 ODM 칸으로 잇는다"""
    from pipeline.value_chain import DEMANDS, NODES
    return [(k, f"{n} — {d}") for k, n, d in DEMANDS] + [(k, f"{n} — {d}") for k, n, _, _, d in NODES]


def schema() -> dict:
    keys = [k for k, _ in node_catalog()] + [""]
    item = {"type": "object", "additionalProperties": False,
            "required": ["source_org", "node_key", "subject", "metric", "target_period", "value_low", "value_high", "unit", "direction", "quote"],
            "properties": {"source_org": {"type": "string"}, "node_key": {"type": "string", "enum": keys}, "subject": {"type": "string"},
                           "metric": {"type": "string", "enum": METRICS}, "target_period": {"type": "string"},
                           "value_low": {"type": ["number", "null"]}, "value_high": {"type": ["number", "null"]}, "unit": {"type": "string"},
                           "direction": {"type": "string", "enum": ["up", "down", "flat"]}, "quote": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["claims"], "properties": {"claims": {"type": "array", "items": item}}}


def _has(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def candidates(conn, backfill: bool = False) -> list[dict]:
    """처리 안 한 최근 문서 중 전망 어휘·기관·밸류체인 낱말이 모두 있는 것(최신순, 상한)"""
    rows = conn.execute(f"""SELECT d.id, d.title, d.url, d.published_at, d.source_type, d.markdown FROM raw_documents d
        LEFT JOIN exp_feed_docs x ON x.doc_id=d.id
        WHERE x.doc_id IS NULL AND d.published_at >= datetime('now','-{DAYS[backfill]} days') AND d.markdown IS NOT NULL
        ORDER BY d.published_at DESC""").fetchall()
    # 같은 기사가 여러 출처(텔레그램·블로그)로 들어온다 — 최근 처리한 제목과 이번 묶음 안의 같은 제목은 건너뛴다
    seen = {(t or "").strip() for (t,) in conn.execute(
        "SELECT d.title FROM exp_feed_docs x JOIN raw_documents d ON d.id=x.doc_id WHERE x.processed_at >= datetime('now','-14 days')")}
    out = []
    for r in rows:
        title = (r["title"] or "").strip()
        text = f"{title}\n{r['markdown'] or ''}"
        if title and title in seen:
            continue
        if _has(text, FORECAST) and _has(text, ORGS) and _has(text, CHIP):
            seen.add(title)
            out.append(dict(r))
        if len(out) >= CAP[backfill]:
            break
    return out


_WS = re.compile(r"\s+")


def quote_in_doc(quote: str, text: str) -> bool:
    """환각 방지 — 인용문 앞 40자(공백 정규화)가 문서에 있어야 한다"""
    q = _WS.sub("", quote or "")[:40]
    return len(q) >= 8 and q in _WS.sub("", text or "")


def extract(doc: dict) -> tuple[list[dict], int]:
    """문서 1건 → (원문 확인된 전망, 버린 수)"""
    from pipeline.llm import run
    nodes = "\n".join(f"- {k}: {n}" for k, n in node_catalog())
    text = (doc["markdown"] or "")[:DOC_CHARS]
    prompt = (f"## 밸류체인 칸 목록(key: 이름)\n{nodes}\n\n## 문서\n제목: {doc['title']}\n날짜: {doc['published_at']}\n출처 유형: {doc['source_type']}\n\n{text}\n\n"
              "위 문서에서 전망만 뽑아라.")
    res = run(prompt, system=SYSTEM, model=MODEL, timeout=180, job="exp_feed", json_schema=schema())
    data = json.loads(res.text) if isinstance(res.text, str) else res.text
    claims = data.get("claims", []) if isinstance(data, dict) else []
    kept = [c for c in claims if quote_in_doc(c.get("quote", ""), f"{doc['title']}\n{doc['markdown']}") and c.get("source_org")]
    return kept, len(claims) - len(kept)


def _mark(doc_id: int, status: str, n: int = 0, dropped: int = 0, error: str | None = None) -> None:
    from database import get_connection
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO exp_feed_docs (doc_id, status, n_claims, n_dropped, error, processed_at) VALUES (?,?,?,?,?, datetime('now'))",
                     (doc_id, status, n, dropped, error))
        conn.commit()
    finally:
        conn.close()


def _store(doc: dict, claims: list[dict]) -> None:
    from database import get_connection
    conn = get_connection()
    try:
        for c in claims:
            conn.execute(
                "INSERT INTO expectation_claims (source, source_org, published_at, node_key, subject, metric, target_period, value_low, value_high,"
                " unit, direction, quote, url, doc_id) VALUES ('feed',?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(source, url, node_key, subject, metric, target_period) DO UPDATE SET source_org=excluded.source_org,"
                " value_low=excluded.value_low, value_high=excluded.value_high, unit=excluded.unit, direction=excluded.direction, quote=excluded.quote",
                (norm_org(c["source_org"]), doc["published_at"], c["node_key"] or "", c["subject"] or "", c["metric"], c["target_period"] or "",
                 c["value_low"], c["value_high"], c["unit"], c["direction"], c["quote"][:300], doc["url"] or f"doc:{doc['id']}", doc["id"]))
        conn.commit()
    finally:
        conn.close()


def collect(backfill: bool = False) -> dict:
    """후보 문서마다 추출 → 원문 확인 → 저장. LLM 호출 중에는 DB 연결을 잡지 않는다"""
    from database import get_connection
    conn = get_connection()
    try:
        docs = candidates(conn, backfill)
    finally:
        conn.close()
    stored = dropped = none = 0
    errors = []
    for d in docs:
        try:
            claims, drop = extract(d)
        except Exception as e:  # noqa: BLE001 — 한 문서 실패는 기록하고 다음으로(다음 실행에서 다시 시도하지 않게 error로 표시)
            _mark(d["id"], "error", error=f"{type(e).__name__}: {str(e)[:200]}")
            errors.append(d["id"])
            continue
        if claims:
            _store(d, claims)
        _mark(d["id"], "ok" if claims else "none", len(claims), drop)
        stored += len(claims)
        dropped += drop
        none += 0 if claims else 1
    status = "error" if docs and len(errors) == len(docs) else "partial" if errors else "ok"
    return {"status": status, "docs": len(docs), "stored": stored, "dropped_unquoted": dropped, "no_forecast": none,
            **({"error": f"추출 실패 문서 {len(errors)}건: {errors[:5]}"} if errors else {})}

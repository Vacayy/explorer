"""미국 기업 실적 컨콜 transcript 수집 (docs/specs/transcript-follow.md).

핵심 원칙 (사일로 금지): transcript 전문은 별도 테이블에 가두지 않고 raw_documents
(source_type='transcript')로 넣는다. 그러면 기존 파이프라인이 자동으로 인수한다 —
  enrich(태깅→entity_links) → doc_causal(인과 추출→entity_relations=온톨로지)
  → digests(LLM 정리) → doc_vec(RAG).
여기 transcripts 테이블은 팔로우/프록시 UI용 얇은 인덱스일 뿐(전문 중복 저장 안 함).

Provider 추상 — 한 제공처에 락인되지 않게 어댑터로. TRANSCRIPT_PROVIDER env로 스위치.
1차 구현은 FMP(무료 티어 250 req/day + dates-by-symbol 폴링). 필요 시 earningscall/alphavantage 추가.
"""
import time
from datetime import date, datetime, timezone
from typing import Protocol

import requests

from config import ALPHAVANTAGE_API_KEY, FMP_API_KEY, TRANSCRIPT_PROVIDER
from database import get_connection
from pipeline.base import RawDoc
from pipeline.store import store_document

# 기본 팔로우 세트 (사용자 확정 2026-07-23, 확대 2026-07-27 D-075).
# 미국 위주. 2026-07-27 확대로 AI 반도체 공급망(메모리·파운드리·semicap)·AI DC 물리인프라(전력·냉각)·
# SW까지 넓힘. ASML(네덜란드)·TSM(대만)은 미국 상장 ADR/주식 — 사용자 명시 요청으로 포함(전공정 앵커).
# ⚠️ Alpha Vantage EARNINGS_CALL_TRANSCRIPT의 해외 발행사 커버리지는 제한적일 수 있음(수집 후 확인 필요).
DEFAULT_FOLLOWS = [
    ("AAPL", "Apple", "M7"), ("MSFT", "Microsoft", "M7"), ("GOOGL", "Alphabet", "M7"),
    ("AMZN", "Amazon", "M7"), ("META", "Meta", "M7"), ("NVDA", "NVIDIA", "M7"), ("TSLA", "Tesla", "M7"),
    ("ORCL", "Oracle", "hyperscaler"),
    ("AVGO", "Broadcom", "nasdaq"), ("AMD", "AMD", "nasdaq"),
    ("CRWV", "CoreWeave", "ai-datacenter"), ("IREN", "IREN", "ai-datacenter"), ("NBIS", "Nebius", "ai-datacenter"),
    ("RKLB", "Rocket Lab", "space"),
    ("VST", "Vistra", "energy"), ("CEG", "Constellation Energy", "energy"),
    ("COHR", "Coherent", "cpo"), ("LITE", "Lumentum", "cpo"),
    ("SNOW", "Snowflake", "software"),
    ("COIN", "Coinbase", "web3"), ("HOOD", "Robinhood", "web3"),
    # ── 확대 2026-07-27 (D-075): AI 반도체 공급망 ──
    ("MU", "Micron", "memory"),
    ("TSM", "TSMC", "foundry"),
    ("ASML", "ASML", "semicap"), ("AMAT", "Applied Materials", "semicap"),
    ("LRCX", "Lam Research", "semicap"), ("KLAC", "KLA", "semicap"),
    ("ANET", "Arista Networks", "networking"), ("MRVL", "Marvell", "networking"),
    ("DELL", "Dell Technologies", "server"), ("SMCI", "Super Micro Computer", "server"),
    # ── AI 데이터센터 물리 인프라(전력·냉각)·SW ──
    ("VRT", "Vertiv", "dc-infra"), ("ETN", "Eaton", "dc-infra"), ("GEV", "GE Vernova", "power"),
    ("PLTR", "Palantir", "software"),
]

# Alpha Vantage 트랜스크립트 미커버 종목 (D-081) — 해외 발행사(ADR). 신규 설치 시 active=0으로
# 수집 대상에서 제외(예산 낭비 방지). 팔로우 기록은 유지 — 나중에 유료 소스 붙이면 재활성.
AV_UNCOVERED = {"ASML", "TSM"}


class TranscriptProvider(Protocol):
    name: str
    def list_available(self, ticker: str) -> list[dict]: ...   # [{year, quarter, date}]
    def fetch(self, ticker: str, year: int, quarter: int) -> dict | None: ...  # {date, content}


class FMPProvider:
    """Financial Modeling Prep — stable 엔드포인트. 무료 티어로 시작 가능."""
    name = "fmp"
    BASE = "https://financialmodelingprep.com/stable"

    def _get(self, path: str, **params) -> list | dict | None:
        if not FMP_API_KEY:
            raise RuntimeError("FMP_API_KEY 미설정 — .env에 발급 키를 넣어주세요 (무료: financialmodelingprep.com)")
        params["apikey"] = FMP_API_KEY
        r = requests.get(f"{self.BASE}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def list_available(self, ticker: str) -> list[dict]:
        # /earning-call-transcript-dates?symbol=X → [{quarter, fiscalYear|year, date}] (또는 레거시 [[q,y,date]])
        rows = self._get("earning-call-transcript-dates", symbol=ticker) or []
        out = []
        for row in rows:
            if isinstance(row, dict):
                y = row.get("fiscalYear") or row.get("year")
                q = row.get("quarter") or row.get("period")
                d = row.get("date")
            elif isinstance(row, (list, tuple)) and len(row) >= 3:
                q, y, d = row[0], row[1], row[2]
            else:
                continue
            if y and q:
                out.append({"year": int(y), "quarter": int(str(q).lstrip("Q") or 0), "date": d})
        return out

    def fetch(self, ticker: str, year: int, quarter: int) -> dict | None:
        data = self._get("earning-call-transcript", symbol=ticker, year=year, quarter=quarter) or []
        if not data:
            return None
        row = data[0] if isinstance(data, list) else data
        content = (row.get("content") or "").strip()
        if not content:
            return None
        return {"date": row.get("date", ""), "content": content}


def _recent_quarters(n: int = 5) -> list[dict]:
    """AV 조회용 후보 분기 (연,분기) 내림차순. **AV는 dates 엔드포인트가 없고 회계분기로 라벨링**한다 —
    6월 결산사(MSFT)의 회계 Q4는 캘린더 Q3(7월)에 발표되며 라벨은 `연Q4`, 1월 결산사(NVDA)는 회계연도가
    캘린더보다 앞서 `차년Q1` 라벨을 쓴다. 따라서 캘린더 분기만으론 라벨을 못 맞춘다 → **캘린더보다 한 해 앞
    (당해 Q4·차년 Q1 포함)부터 넓게 생성**. 없는 라벨은 빈응답 → 네거티브 캐시가 억제.
    (D-084: 기존 '캘린더 q-1부터' 방식은 MSFT류 회계 Q4 라벨을 영영 생성 못 해 신규 콜을 놓쳤음)."""
    today = date.today()
    y, q = today.year + 1, 1   # 한 해 앞 Q1부터 (회계연도-선행·회계 Q4 커버)
    out = []
    for _ in range(n):
        out.append({"year": y, "quarter": q, "date": f"{y}-{q * 3:02d}-01"})
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


class AlphaVantageProvider:
    """Alpha Vantage — EARNINGS_CALL_TRANSCRIPT. 무료 티어(25 req/day) 포함, 화자 세그먼트 반환.
    dates 엔드포인트가 없어 list_available은 최근 분기 후보를 생성한다."""
    name = "alphavantage"
    URL = "https://www.alphavantage.co/query"

    def list_available(self, ticker: str) -> list[dict]:
        return _recent_quarters(6)

    def fetch(self, ticker: str, year: int, quarter: int) -> dict | None:
        if not ALPHAVANTAGE_API_KEY:
            raise RuntimeError("ALPHAVANTAGE_API_KEY 미설정 — .env에 무료 키를 넣어주세요 (alphavantage.co/support)")
        r = requests.get(self.URL, params={
            "function": "EARNINGS_CALL_TRANSCRIPT", "symbol": ticker,
            "quarter": f"{year}Q{quarter}", "apikey": ALPHAVANTAGE_API_KEY}, timeout=30)
        r.raise_for_status()
        j = r.json()
        # 레이트리밋·프리미엄 안내는 Information/Note로 옴 — 조용히 스킵(거짓 데이터 금지)
        if "Information" in j or "Note" in j or "Error Message" in j:
            print(f"[transcript] AV {ticker} {year}Q{quarter}: {j.get('Information') or j.get('Note') or j.get('Error Message')}")
            return None
        segs = j.get("transcript") or []
        if not segs:
            return None
        # 화자 라벨 보존 마크다운 — doc_causal이 '누가 무엇을 주장했나'를 살리도록
        body = "\n\n".join(
            f"**{s.get('speaker', '')}**{f' ({s['title']})' if s.get('title') else ''}: {s.get('content', '')}"
            for s in segs if s.get("content"))
        if not body.strip():
            return None
        return {"date": f"{year}-{quarter * 3:02d}-01", "content": body}  # AV는 콜 날짜 미제공 → 분기 근사


def get_provider() -> TranscriptProvider:
    if TRANSCRIPT_PROVIDER == "alphavantage":
        return AlphaVantageProvider()
    if TRANSCRIPT_PROVIDER == "fmp":
        return FMPProvider()
    raise NotImplementedError(f"provider '{TRANSCRIPT_PROVIDER}' 미구현 — alphavantage|fmp 지원")


def seed_default_follows() -> int:
    """기본 팔로우 세트를 transcript_follow에 적재 (멱등)."""
    conn = get_connection()
    n = 0
    for ticker, name, group in DEFAULT_FOLLOWS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO transcript_follow (ticker, company_name, group_label) VALUES (?, ?, ?)",
            (ticker, name, group),
        )
        n += cur.rowcount
    # AV 미커버(해외 발행사)는 수집 대상에서 제외 (D-081)
    conn.executemany("UPDATE transcript_follow SET active=0 WHERE ticker=?", [(t,) for t in AV_UNCOVERED])
    conn.commit()
    conn.close()
    return n


_DIGEST_PROMPT = """다음은 미국 상장사의 실적 발표·컨퍼런스콜 전문이다. 한국어 마크다운으로 정리하라.
아래 소제목을 그대로 쓴다. 수치는 원문 그대로 인용. 추측·미사여구 금지 — 원문에 없는 건 쓰지 마라.

앞의 4개 섹션은 각 2~4개 불릿으로 간결하게.

### 실적 하이라이트
### 가이던스·전망
### 경영진 핵심 코멘트
### 리스크·유의점

**Q&A는 가급적 상세하게** 정리한다(애널리스트가 무엇을 물었고 경영진이 어떻게 답했는지가 신호가 큼).
아래 형식으로 **주요 문답을 빠짐없이**, 질문자 소속(있으면)·질문 요지·경영진 답변 핵심(수치·뉘앙스 포함)을 담아라.
답변이 회피/모호하면 그 점도 적는다. 문답이 없으면 "Q&A 없음"만 쓴다.

### Q&A 핵심
- **Q (질문자/소속):** 질문 요지
  - **A:** 경영진 답변 핵심 (수치·가이던스·뉘앙스, 회피 여부)
- (주요 문답마다 반복)

[제목] {title}
[전문]
{body}"""


def digest_one(transcript_id: int) -> str | None:
    """transcript 한 건의 핵심 정리 생성(sonnet) → transcripts.digest 저장. 원문은 그대로 둔다."""
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT t.id, t.raw_doc_id, rd.title, rd.markdown FROM transcripts t "
        "JOIN raw_documents rd ON rd.id = t.raw_doc_id WHERE t.id=?", (transcript_id,)
    ).fetchone()
    if not row or not (row["markdown"] or "").strip():
        conn.close()
        return None
    body = row["markdown"][:60000]  # 과대 입력 방지 (컨콜 앞부분에 실적·가이던스 집중)
    try:
        digest = _call_claude_code(
            _DIGEST_PROMPT.format(title=row["title"] or "", body=body),
            model="sonnet", timeout=300).strip()
    except Exception as e:  # noqa: BLE001
        print(f"[transcript] digest {transcript_id} 실패: {e}")
        conn.close()
        return None
    conn.execute("UPDATE transcripts SET digest=? WHERE id=?", (digest, transcript_id))
    conn.commit()
    conn.close()
    return digest


def digest_pending(limit: int = 10) -> int:
    """정리 미생성(digest IS NULL) transcript를 최신순으로 채운다 (수집 후·cron)."""
    conn = get_connection()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM transcripts WHERE digest IS NULL ORDER BY fiscal_year DESC, id DESC LIMIT ?",
        (limit,)).fetchall()]
    conn.close()
    n = 0
    for tid in ids:
        if digest_one(tid):
            n += 1
    return n


# 프록시 레지스트리 기본 시드 (D-048: 사람이 초기 세팅 → 이후 자동 트래킹) — AI/데이터센터 지배 서사 기준
PROXY_SEED = [
    ("hyperscaler_capex", "하이퍼스케일러 CAPEX 추이", "MSFT,GOOGL,AMZN,META,ORCL", "$B",
     "이번 분기 자본지출(CAPEX) 금액과 전분기·전년 대비 방향, 그리고 차기/연간 CAPEX 가이던스"),
    ("dc_demand_backlog", "AI 데이터센터 수요·백로그", "NVDA,CRWV,IREN,NBIS", "$B",
     "데이터센터/AI 관련 매출·수주잔고(백로그)·캐파 규모와 전분기 대비 방향"),
]


def seed_proxies() -> int:
    conn = get_connection()
    n = 0
    for key, label, tickers, unit, hint in PROXY_SEED:
        cur = conn.execute(
            "INSERT OR IGNORE INTO proxy_registry (key, label, tickers, unit, extract_hint) VALUES (?, ?, ?, ?, ?)",
            (key, label, tickers, unit, hint))
        n += cur.rowcount
    conn.commit()
    conn.close()
    return n


_PROXY_PROMPT = """다음 실적 컨콜 전문에서 아래 지표를 추출하라. 원문에 명시된 수치·발언만 쓰고,
없으면 found=false. 추정·계산 금지.

[지표] {label}
[무엇을 볼지] {hint}

JSON만 출력:
{{"found": true/false, "value_text": "원문 인용 한 문장(수치 포함)", "value_num": 숫자 또는 null,
  "direction": "up"/"down"/"flat"/null}}

[컨콜 전문]
{body}"""


def extract_proxies(limit: int = 40) -> dict:
    """활성 프록시 × 관련 티커의 미추출 transcript에서 지표 값 추출 → proxy_observations.
    멱등: (proxy_id, transcript_id) 이미 있으면 스킵. haiku(값싸게)."""
    import json
    from pipeline.enrich import _call_claude_code, llm_available
    if not llm_available():
        return {"extracted": 0, "skipped": 0, "reason": "llm 미가용"}
    conn = get_connection()
    proxies = conn.execute("SELECT id, key, label, tickers, unit, extract_hint FROM proxy_registry WHERE active=1").fetchall()
    extracted, scanned = 0, 0
    for p in proxies:
        tickers = [t.strip() for t in (p["tickers"] or "").split(",") if t.strip()]
        rows = conn.execute(
            "SELECT t.id, t.ticker, t.call_date, rd.markdown FROM transcripts t "
            "JOIN raw_documents rd ON rd.id = t.raw_doc_id "
            f"WHERE t.ticker IN ({','.join('?' * len(tickers))}) "
            "ORDER BY t.fiscal_year DESC LIMIT ?", (*tickers, limit)).fetchall() if tickers else []
        for r in rows:
            if scanned >= limit:
                break
            exists = conn.execute(
                "SELECT 1 FROM proxy_observations WHERE proxy_id=? AND transcript_id=?", (p["id"], r["id"])).fetchone()
            if exists:
                continue
            scanned += 1
            try:
                raw = _call_claude_code(
                    _PROXY_PROMPT.format(label=p["label"], hint=p["extract_hint"] or "", body=(r["markdown"] or "")[:40000]),
                    model="haiku", timeout=180)
                d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            except Exception as e:  # noqa: BLE001
                print(f"[proxy] {p['label']} {r['ticker']} 실패: {e}")
                continue
            if not d.get("found"):
                continue
            conn.execute(
                "INSERT INTO proxy_observations "
                "(proxy_id, transcript_id, source_type, source_id, observed_at, value_num, value_text, direction) "
                "VALUES (?, ?, 'transcript', ?, ?, ?, ?, ?)",
                (p["id"], r["id"], str(r["id"]), r["call_date"], d.get("value_num"), d.get("value_text"), d.get("direction")))
            conn.commit()
            extracted += 1
    conn.close()
    project_numeric_observations()   # 그래프 결합 (D-067 2c) — 멱등 배치
    return {"extracted": extracted, "scanned": scanned}


def project_numeric_observations() -> int:
    """numeric 프록시 관측을 observations(엔티티 노드)에 투영 — 그래프 결합(D-067 2c), 잠자던 테이블 가동.
    transcript_id→ticker→transcript_follow.entity_id 경유. 멱등(INSERT OR IGNORE)."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO observations (entity_id, date, metric, value, unit, source) "
        "SELECT tf.entity_id, po.observed_at, pr.key, po.value_num, pr.unit, 'proxy:transcript' "
        "FROM proxy_observations po "
        "JOIN transcripts t ON t.id = po.transcript_id "
        "JOIN transcript_follow tf ON tf.ticker = t.ticker "
        "JOIN proxy_registry pr ON pr.id = po.proxy_id "
        "WHERE po.source_type='transcript' AND po.value_num IS NOT NULL "
        "  AND tf.entity_id IS NOT NULL AND po.observed_at IS NOT NULL")
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def _followed(only: list[str] | None = None) -> list[dict]:
    conn = get_connection()
    q = "SELECT ticker, company_name, group_label FROM transcript_follow WHERE active=1"
    rows = [dict(r) for r in conn.execute(q).fetchall()]
    conn.close()
    if only:
        rows = [r for r in rows if r["ticker"] in only]
    return rows


def _existing_periods(ticker: str) -> set:
    conn = get_connection()
    rows = conn.execute(
        "SELECT fiscal_year, fiscal_period FROM transcripts WHERE ticker=?", (ticker,)
    ).fetchall()
    conn.close()
    return {(r["fiscal_year"], r["fiscal_period"]) for r in rows}


def _feed_ts() -> str:
    """transcript 피드 정렬용 published_at = 수집 시각(UTC ISO). AV는 실제 콜 날짜를 안 줘
    회계분기 근사(YYYY-분기*3-01)를 published_at에 쓰면 미래로 찍혀 피드 '최신순'을 깬다
    → 수집 시각으로. 분기 정체성은 call_date·fiscal_year/period가 별도 보존(목록은 그쪽 정렬)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store_call(provider, f: dict, year: int, quarter: int) -> bool:
    """한 (기업, 분기) 수집 → raw_documents + transcripts. 저장 성공 시 True."""
    got = provider.fetch(f["ticker"], year, quarter)
    if not got:
        return False
    period = f"Q{quarter}" if quarter else "FY"
    source_id = f"{f['ticker']}:{year}:{period}"
    doc = RawDoc(
        source_type="transcript", source_id=source_id,
        title=f"{f['company_name']} ({f['ticker']}) FY{year} {period} 실적 컨퍼런스콜",
        published_at=_feed_ts(), raw_content=got["content"], kind="text")
    res = store_document(doc)   # raw_documents INSERT + enrich 인라인
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO transcripts (raw_doc_id, ticker, fiscal_year, fiscal_period, call_date, provider) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (res["doc_id"], f["ticker"], year, period, got["date"], provider.name))
    conn.commit()
    conn.close()
    # 수집 즉시 인과 추출 (D-089) — cron 대기 없이 그 건을 바로 온톨로지에 편입. 컨콜=고신호 인과원.
    if res.get("status") in ("new", "updated"):
        try:
            from pipeline.doc_causal import extract_for_doc
            extract_for_doc(res["doc_id"])
        except Exception as e:  # noqa: BLE001 — 추출 실패가 수집을 막지 않게 (cron 배치가 후속 치유)
            print(f"[transcript] 즉시 doc_causal 실패 doc {res['doc_id']}: {e}")
    return True


def refresh_calendar(tickers: list[str], max_age_hours: int = 24) -> int:
    """yfinance로 최근/차기 실적 발표일 캐시 (무료 — AV 25/day 예산과 무관, D-081).
    max_age 내 최신 캐시는 스킵. 실패는 무시. **UI 표시·발표일 참고용**(D-084: 수집 게이트 폐지)."""
    import yfinance as yf
    import pandas as pd
    conn = get_connection()
    fresh = {r[0] for r in conn.execute(
        "SELECT ticker FROM transcript_calendar WHERE checked_at > datetime('now', ?)",
        (f"-{max_age_hours} hours",)).fetchall()}
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    for tk in tickers:
        if tk in fresh:
            continue
        last = nxt = None
        try:
            df = yf.Ticker(tk).get_earnings_dates(limit=8)
            if df is not None and len(df):
                for idx, row in df.iterrows():
                    dstr = idx.date().isoformat()
                    if pd.notna(row.get("Reported EPS", None)):
                        if last is None or dstr > last:
                            last = dstr
                    elif dstr >= today and (nxt is None or dstr < nxt):
                        nxt = dstr
        except Exception as e:  # noqa: BLE001
            print(f"[calendar] {tk} 조회 실패(무시): {e}")
        conn.execute(
            "INSERT INTO transcript_calendar (ticker, last_report_date, next_report_date, checked_at) "
            "VALUES (?, ?, ?, datetime('now')) ON CONFLICT(ticker) DO UPDATE SET "
            "last_report_date=excluded.last_report_date, next_report_date=excluded.next_report_date, "
            "checked_at=datetime('now')", (tk, last, nxt))
        conn.commit()
        n += 1
    conn.close()
    return n


def _yf_call_dates(ticker: str) -> dict:
    """yfinance로 (회계연도, 분기)→실제 발표일 매핑 (D-084). AV는 콜 날짜를 안 줘 회계분기 라벨만 오므로,
    결산월(lastFiscalYearEnd) + 분기말(quarterly_income_stmt) + 실적일(get_earnings_dates)로 라벨↔날짜 정합.
    분기말 pe의 라벨: q = 4 - ((결산월-pe.월) % 12)//3, fy = pe.년(+1 if pe.월>결산월). 실패 시 {}."""
    import yfinance as yf
    import pandas as pd
    try:
        t = yf.Ticker(ticker)
        ts = (t.info or {}).get("lastFiscalYearEnd")
        if not ts:
            return {}
        fye_month = datetime.fromtimestamp(ts, timezone.utc).month
        qis = t.quarterly_income_stmt
        period_ends = sorted([c.date() for c in qis.columns], reverse=True) if qis is not None and len(qis.columns) else []
        ed = t.get_earnings_dates(limit=16)
        reps = sorted([idx.date() for idx, r in ed.iterrows() if pd.notna(r.get("Reported EPS", None))])
    except Exception as e:  # noqa: BLE001
        print(f"[call-date] {ticker} yfinance 실패(무시): {e}")
        return {}
    out = {}
    for pe in period_ends:
        cand = [d for d in reps if d >= pe]     # 분기말 이후 첫 실적일 = 발표일
        if not cand:
            continue
        q = 4 - (((fye_month - pe.month) % 12) // 3)
        fy = pe.year if pe.month <= fye_month else pe.year + 1
        out[(fy, q)] = min(cand).isoformat()
    return out


def backfill_call_dates(only: list[str] | None = None, set_published: bool = True) -> dict:
    """저장된 transcripts.call_date를 실제 발표일로 교정 (D-084). AV 저장 시 분기 근사(YYYY-분기*3-01)라
    헷갈려서 → yfinance 실제 발표일로. set_published면 raw_documents.published_at(피드 정렬)도 함께.
    회계분기(Q1~Q4)만 대상(FY 연간 제외). 매핑 안 되는(윈도 밖·yfinance 실패) 건은 건드리지 않음."""
    conn = get_connection()
    q = "SELECT DISTINCT ticker FROM transcripts"
    tickers = [r["ticker"] for r in conn.execute(q).fetchall()]
    if only:
        tickers = [t for t in tickers if t in only]
    updated, unresolved = 0, 0
    for tk in tickers:
        mapping = _yf_call_dates(tk)
        rows = conn.execute(
            "SELECT id, raw_doc_id, fiscal_year, fiscal_period FROM transcripts WHERE ticker=?", (tk,)).fetchall()
        for r in rows:
            p = (r["fiscal_period"] or "")
            if not p.startswith("Q"):
                continue
            key = (r["fiscal_year"], int(p[1:]))
            real = mapping.get(key)
            if not real:
                unresolved += 1
                continue
            conn.execute("UPDATE transcripts SET call_date=? WHERE id=?", (real, r["id"]))
            if set_published and r["raw_doc_id"]:
                conn.execute("UPDATE raw_documents SET published_at=? WHERE id=?", (real, r["raw_doc_id"]))
            updated += 1
    conn.commit()
    conn.close()
    return {"updated": updated, "unresolved": unresolved, "tickers": len(tickers)}


def _bucket_map(sql: str, params: tuple = ()) -> dict:
    """(ticker → {(year, period)}) 벌크 로드 — 루프 내 커넥션 N×M 방지."""
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    out: dict = {}
    for r in rows:
        out.setdefault(r["ticker"], set()).add((r["fiscal_year"], r["fiscal_period"]))
    return out


def _record_empty(ticker: str, year: int, period: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO transcript_probe (ticker, fiscal_year, fiscal_period) VALUES (?, ?, ?) "
        "ON CONFLICT(ticker, fiscal_year, fiscal_period) DO UPDATE SET "
        "attempts = attempts + 1, checked_at = datetime('now')", (ticker, year, period))
    conn.commit()
    conn.close()


def collect_roundrobin(request_budget: int = 24, ranks: int = 12, sleep_s: float = 13.0,
                       only: list[str] | None = None, cooldown_days: int = 45,
                       use_calendar: bool = True, dry_run: bool = False) -> dict:
    """분기-랭크 라운드로빈 — 모든 기업의 최신 분기 먼저, 그 다음 이전 분기.
    Alpha Vantage 무료 한도(25/day·5/min) 대응: request_budget 상한 + 요청 간 sleep.
    낭비 차단: **빈응답 네거티브 캐시**(cooldown_days 내 빈 (기업,분기) 재요청 안 함) + 저장분 스킵.
    (D-084: D-081의 '캘린더 게이트'는 AV가 회계분기로 라벨링해 회계연도 어긋난 종목[MSFT·NVDA 등]의
    수집가능 분기를 false-skip → 제거. 캘린더는 UI 표시·발표일 참고용으로만 유지.)
    use_calendar=True면 수집 김에 발표일 캐시도 갱신(UI용). dry_run=True면 fetch 없이 계획만."""
    provider = get_provider()
    companies = _followed(only)
    if use_calendar and not dry_run:
        try:
            refresh_calendar([c["ticker"] for c in companies])   # UI용 발표일 캐시 (게이트 아님)
        except Exception as e:  # noqa: BLE001
            print(f"[calendar] 갱신 실패(무시): {e}")
    cands = _recent_quarters(ranks)   # 최신순
    existing = _bucket_map("SELECT ticker, fiscal_year, fiscal_period FROM transcripts")
    empties = _bucket_map(
        "SELECT ticker, fiscal_year, fiscal_period FROM transcript_probe WHERE checked_at > datetime('now', ?)",
        (f"-{cooldown_days} days",))
    used, stored, empty, skip_cache = 0, 0, 0, 0
    planned: list[str] = []
    done = False
    for q in cands:                    # 랭크(분기) 바깥 = 최신 분기부터
        if done:
            break
        period = f"Q{q['quarter']}"
        for f in companies:            # 기업 안쪽 = 그 분기를 전 기업에 걸쳐
            tk = f["ticker"]
            if (q["year"], period) in existing.get(tk, ()):
                continue               # 저장됨 — 요청 없이 스킵
            if (q["year"], period) in empties.get(tk, ()):
                skip_cache += 1        # 최근 빈응답 — 네거티브 캐시
                continue
            if dry_run:
                planned.append(f"{tk} {q['year']}{period}")
                continue
            if used >= request_budget:
                done = True
                break
            if used > 0:
                time.sleep(sleep_s)    # 5 req/min 준수
            try:
                ok = _store_call(provider, f, q["year"], q["quarter"])
            except Exception as e:      # noqa: BLE001
                print(f"[transcript] {tk} {q['year']}{period} 실패: {e}")
                used += 1
                continue
            used += 1
            if ok:
                stored += 1
                print(f"[transcript] +{tk} {q['year']}{period}")
            else:
                empty += 1
                _record_empty(tk, q["year"], period)   # 빈응답 기억 → 재요청 차단
    if dry_run:
        return {"dry_run": True, "would_request": len(planned), "planned": planned,
                "skipped_cache": skip_cache}
    return {"requests": used, "stored": stored, "empty": empty, "budget": request_budget,
            "skipped_cache": skip_cache, "exhausted": done}


def collect_and_process(budget: int = 22, only: list[str] | None = None) -> dict:
    """수집 전체 사슬 — 라운드로빈 수집 → 발표일 교정 → 핵심 정리 → 프록시 추출 (D-121).

    cron 스크립트와 UI 버튼이 **같은 코드**를 타게 하려고 여기로 올렸다(전엔 스크립트 안에
    인라인 `_work`였다). 버튼이 '지금 돌리기'인데 사슬이 다르면 결과가 갈린다.
    호출자가 `run_job`으로 감싸 플래그 게이트·실행 로그를 붙인다.
    """
    r = collect_roundrobin(request_budget=budget, only=only)
    print(f"[transcript] 요청 {r['requests']}/{r['budget']} · 신규 {r['stored']}건 적재 · "
          f"빈응답 {r['empty']} · 캐시 스킵 {r['skipped_cache']} · 예산소진={r['exhausted']}")
    if r["stored"]:
        bc = backfill_call_dates(only=only)   # 신규분 call_date를 실제 발표일로 (yfinance, D-084)
        print(f"[transcript] 발표일 교정 {bc['updated']}건")
    n = digest_pending(limit=max(r["stored"], 5))   # 신규분 핵심 정리 생성(sonnet)
    print(f"[transcript] 핵심 정리 {n}건 생성")
    seed_proxies()
    px = extract_proxies()                          # 관찰 프록시 트래킹 (haiku, 멱등)
    print(f"[transcript] 프록시 추출 {px.get('extracted', 0)}건")
    return {**r, "digested": n, "proxies": px.get("extracted", 0)}


def collect_followed(only: list[str] | None = None, max_new_per_ticker: int = 4) -> dict:
    """팔로우 기업의 신규 컨콜을 수집 → raw_documents 적재 → transcripts 인덱스.
    이후 enrich·doc_causal·digests는 기존 파이프라인이 인수(온톨로지 편입은 doc_causal cron에서).
    max_new_per_ticker: 최신순으로 티커당 신규 N건만 (첫 실행 폭주 방지)."""
    provider = get_provider()
    follows = _followed(only)
    stored, skipped, failed = 0, 0, 0
    for f in follows:
        ticker = f["ticker"]
        try:
            avail = provider.list_available(ticker)
        except Exception as e:  # noqa: BLE001 — 티커 하나 실패가 전체를 막지 않게
            print(f"[transcript] {ticker} list 실패: {e}")
            failed += 1
            continue
        have = _existing_periods(ticker)
        # 최신(연도·분기 큰 것) 우선
        avail.sort(key=lambda a: (a["year"], a["quarter"]), reverse=True)
        new_count = 0
        for item in avail:
            if new_count >= max_new_per_ticker:
                break
            period = f"Q{item['quarter']}" if item["quarter"] else "FY"
            if (item["year"], period) in have:
                skipped += 1
                continue
            try:
                got = provider.fetch(ticker, item["year"], item["quarter"])
            except Exception as e:  # noqa: BLE001
                print(f"[transcript] {ticker} {item['year']}{period} fetch 실패: {e}")
                failed += 1
                continue
            if not got:
                continue
            source_id = f"{ticker}:{item['year']}:{period}"
            doc = RawDoc(
                source_type="transcript",
                source_id=source_id,
                title=f"{f['company_name']} ({ticker}) FY{item['year']} {period} 실적 컨퍼런스콜",
                published_at=_feed_ts(),
                raw_content=got["content"],
                kind="text",
            )
            res = store_document(doc)  # raw_documents INSERT + enrich 인라인
            conn = get_connection()
            conn.execute(
                "INSERT OR IGNORE INTO transcripts (raw_doc_id, ticker, fiscal_year, fiscal_period, call_date, provider) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (res["doc_id"], ticker, item["year"], period, got["date"] or item.get("date"), provider.name),
            )
            conn.commit()
            conn.close()
            stored += 1
            new_count += 1
    return {"stored": stored, "skipped": skipped, "failed": failed, "tickers": len(follows)}

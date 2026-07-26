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
from datetime import date
from typing import Protocol

import requests

from config import ALPHAVANTAGE_API_KEY, FMP_API_KEY, TRANSCRIPT_PROVIDER
from database import get_connection
from pipeline.base import RawDoc
from pipeline.store import store_document

# 기본 팔로우 세트 (사용자 확정 2026-07-23) — 미국 상장사만, 전력반도체·바이오 제외, 비상장 제외
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
]


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
    """최근 n개 캘린더 분기 (연,분기) 내림차순. Alpha Vantage는 dates 엔드포인트가 없어
    직접 분기를 지목해 조회하므로 최근 분기 후보를 생성한다(없는 분기는 빈 응답 → 스킵)."""
    today = date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    # 현재 캘린더 분기는 대개 미보고 → 직전 분기부터 조회(빈응답 낭비 방지). 회계연도-선행 기업(NVDA 등)의
    # 이미-보고분은 저장돼 있어 스킵되므로 손실 없음. n을 1 늘려 커버 폭 유지.
    q -= 1
    if q == 0:
        q, y = 4, y - 1
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
    conn.commit()
    conn.close()
    return n


_DIGEST_PROMPT = """다음은 미국 상장사의 실적 발표·컨퍼런스콜 전문이다. 투자자가 30초에 핵심을 잡도록
한국어 마크다운 불릿으로 정리하라. 아래 4개 소제목을 그대로 쓰고 각 2~4개 불릿. 수치는 원문 그대로 인용.
추측·미사여구 금지 — 원문에 없는 건 쓰지 마라.

### 실적 하이라이트
### 가이던스·전망
### 경영진 핵심 코멘트
### 리스크·유의점

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
    proxies = conn.execute("SELECT id, label, tickers, extract_hint FROM proxy_registry WHERE active=1").fetchall()
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
    return {"extracted": extracted, "scanned": scanned}


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
        published_at=got["date"], raw_content=got["content"], kind="text")
    res = store_document(doc)
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO transcripts (raw_doc_id, ticker, fiscal_year, fiscal_period, call_date, provider) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (res["doc_id"], f["ticker"], year, period, got["date"], provider.name))
    conn.commit()
    conn.close()
    return True


def collect_roundrobin(request_budget: int = 24, ranks: int = 12, sleep_s: float = 13.0,
                       only: list[str] | None = None) -> dict:
    """분기-랭크 라운드로빈 — 모든 기업의 최신 분기 먼저, 그 다음 이전 분기(사용자 지정 순서).
    Alpha Vantage 무료 한도(25/day·5/min) 대응: request_budget으로 하루 요청 상한, 요청 간 sleep.
    이미 저장된 (기업,분기)는 요청 없이 스킵 → 매일 재실행하면 backlog가 이어서 채워진다.
    (AV는 dates 엔드포인트가 없어 후보 분기를 probe하므로 미보고/회계·달력 분기 불일치 시 빈 응답=요청 소모)."""
    provider = get_provider()
    companies = _followed(only)
    cands = _recent_quarters(ranks)   # 최신순
    used, stored, empty = 0, 0, 0
    done = False
    for q in cands:                    # 랭크(분기) 바깥 = 최신 분기부터
        if done:
            break
        period = f"Q{q['quarter']}"
        for f in companies:            # 기업 안쪽 = 그 분기를 전 기업에 걸쳐
            if used >= request_budget:
                done = True
                break
            if (q["year"], period) in _existing_periods(f["ticker"]):
                continue               # 저장됨 — 요청 없이 스킵
            if used > 0:
                time.sleep(sleep_s)    # 5 req/min 준수
            try:
                ok = _store_call(provider, f, q["year"], q["quarter"])
            except Exception as e:      # noqa: BLE001
                print(f"[transcript] {f['ticker']} {q['year']}{period} 실패: {e}")
                used += 1
                continue
            used += 1
            if ok:
                stored += 1
                print(f"[transcript] +{f['ticker']} {q['year']}{period}")
            else:
                empty += 1
    return {"requests": used, "stored": stored, "empty": empty, "budget": request_budget,
            "exhausted": done}


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
                published_at=got["date"] or item.get("date") or "",
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

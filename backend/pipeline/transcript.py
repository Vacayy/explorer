"""미국 기업 실적 컨콜 transcript 수집 (docs/specs/transcript-follow.md).

핵심 원칙 (사일로 금지): transcript 전문은 별도 테이블에 가두지 않고 raw_documents
(source_type='transcript')로 넣는다. 그러면 기존 파이프라인이 자동으로 인수한다 —
  enrich(태깅→entity_links) → doc_causal(인과 추출→entity_relations=온톨로지)
  → digests(LLM 정리) → doc_vec(RAG).
여기 transcripts 테이블은 팔로우/프록시 UI용 얇은 인덱스일 뿐(전문 중복 저장 안 함).

Provider 추상 — 한 제공처에 락인되지 않게 어댑터로. TRANSCRIPT_PROVIDER env로 스위치.
1차 구현은 FMP(무료 티어 250 req/day + dates-by-symbol 폴링). 필요 시 earningscall/alphavantage 추가.
"""
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
        return _recent_quarters(5)

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

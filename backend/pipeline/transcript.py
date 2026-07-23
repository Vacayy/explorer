"""미국 기업 실적 컨콜 transcript 수집 (docs/specs/transcript-follow.md).

핵심 원칙 (사일로 금지): transcript 전문은 별도 테이블에 가두지 않고 raw_documents
(source_type='transcript')로 넣는다. 그러면 기존 파이프라인이 자동으로 인수한다 —
  enrich(태깅→entity_links) → doc_causal(인과 추출→entity_relations=온톨로지)
  → digests(LLM 정리) → doc_vec(RAG).
여기 transcripts 테이블은 팔로우/프록시 UI용 얇은 인덱스일 뿐(전문 중복 저장 안 함).

Provider 추상 — 한 제공처에 락인되지 않게 어댑터로. TRANSCRIPT_PROVIDER env로 스위치.
1차 구현은 FMP(무료 티어 250 req/day + dates-by-symbol 폴링). 필요 시 earningscall/alphavantage 추가.
"""
import os
from typing import Protocol

import requests

from config import FMP_API_KEY, TRANSCRIPT_PROVIDER
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


def get_provider() -> TranscriptProvider:
    if TRANSCRIPT_PROVIDER == "fmp":
        return FMPProvider()
    raise NotImplementedError(f"provider '{TRANSCRIPT_PROVIDER}' 미구현 — fmp만 지원 (어댑터 추가 필요)")


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

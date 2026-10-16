"""SEC EDGAR 실적 8-K 수집 — Item 2.02 첨부 EX-99.x(실적 보도자료·CFO 코멘터리) (docs/specs/transcript-momentum.md).

무료·키 없음. SEC는 User-Agent에 연락처를 요구한다(없으면 403) → `.env SEC_USER_AGENT="이름 이메일"`.
미설정이면 수집하지 않고 SecNotConfigured를 올린다(조용히 건너뛰지 않음). 초당 10회 제한 → 요청 사이 0.15초.
첨부 파일명은 회사마다 달라(NVDA: q2fy27pr.htm·q2fy27cfocommentary.htm) 공시 색인의 문서 종류(EX-99.x)로 찾는다.
원문은 raw_documents(source_type='earnings_release')에 enrich 없이 저장하고 회사 엔티티만 링크한다
(백필 수백 건을 문서별 LLM 태깅으로 돌리지 않기 위해 — 이 문서는 모멘텀 추출이 직접 읽는다).
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
import time
from datetime import date, timedelta

import requests

SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings_releases (
    doc_id        INTEGER PRIMARY KEY,
    ticker        TEXT NOT NULL,
    accession     TEXT NOT NULL,
    filing_date   TEXT NOT NULL,
    report_date   TEXT,
    exhibit_type  TEXT NOT NULL,      -- EX-99.1 | EX-99.2 ...
    description   TEXT,
    UNIQUE (accession, exhibit_type)
);
CREATE INDEX IF NOT EXISTS idx_earnings_releases_ticker ON earnings_releases(ticker, filing_date);
"""
BASE = "https://www.sec.gov"
PAUSE = 0.15
MAX_CHARS = 120_000


def ensure_schema(conn: sqlite3.Connection) -> None:
    """회사별 결산 월(SEC fiscalYearEnd, 'MMDD') — AV 컨콜은 회사 회계분기로 이름이 붙어 이걸로 분기 라벨을 계산한다."""
    for col in ("fiscal_year_end TEXT", "sic TEXT", "market_cap REAL"):   # sic = SEC 산업분류(사업분류 정렬), market_cap = 정렬·수집 우선순위
        try:
            conn.execute(f"ALTER TABLE transcript_follow ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass


# SEC SIC 코드 → 거친 사업분류(컨콜 목록 '사업분류순'). 기존 팔로우의 손으로 붙인 그룹이 우선이고, NDX 추가 종목에만 쓴다.
SIC_GROUPS = [((7340, 7349), "인터넷 플랫폼·서비스"), ((7380, 7389), "인터넷 플랫폼·서비스"), ((3530, 3533), "에너지·자원"),
              ((3570, 3579), "하드웨어·컴퓨터"), ((3670, 3679), "반도체·전자부품"), ((3559, 3559), "반도체 장비"), ((3825, 3829), "반도체 장비"),
              ((3660, 3669), "통신장비"), ((3600, 3699), "전기·전자"), ((7370, 7379), "소프트웨어·인터넷"), ((2830, 2836), "제약·바이오"),
              ((3840, 3851), "의료기기"), ((8000, 8099), "헬스케어 서비스"), ((4800, 4899), "통신·미디어"), ((4900, 4999), "전력·유틸리티"),
              ((5000, 5999), "유통·소비"), ((2000, 2099), "음식료"), ((3711, 3716), "자동차"), ((3720, 3729), "항공우주"),
              ((6000, 6799), "금융"), ((4000, 4799), "운송·여행"), ((7000, 7099), "운송·여행"), ((7810, 7999), "엔터테인먼트"),
              ((1000, 1499), "에너지·자원"), ((2900, 2999), "에너지·자원"), ((8700, 8799), "전문 서비스"),
              ((2800, 2829), "소재·화학"), ((2700, 2799), "통신·미디어"), ((2200, 2399), "산업 서비스"),
              ((1500, 1799), "산업재·장비"), ((3400, 3569), "산업재·장비"), ((3580, 3599), "산업재·장비"), ((3800, 3824), "산업재·장비")]


def industry_label(sic: str | None) -> str | None:
    if not sic or not str(sic).isdigit():
        return None
    n = int(sic)
    return next((label for (lo, hi), label in SIC_GROUPS if lo <= n <= hi), "기타")


class SecNotConfigured(RuntimeError):
    pass


def _ua() -> dict:
    ua = (os.getenv("SEC_USER_AGENT") or "").strip()
    if "@" not in ua:
        raise SecNotConfigured("SEC_USER_AGENT(연락처 이메일 포함)가 .env에 없습니다 — SEC는 연락처 없는 요청을 거부합니다.")
    return {"User-Agent": ua}


def _get(url: str, as_json: bool = False):
    r = requests.get(url, headers=_ua(), timeout=30)
    time.sleep(PAUSE)
    r.raise_for_status()
    return r.json() if as_json else r.text


_cik_cache: tuple[float, dict[str, int]] | None = None


def cik_map() -> dict[str, int]:
    global _cik_cache
    if _cik_cache and time.time() - _cik_cache[0] < 86400:
        return _cik_cache[1]
    data = _get(f"{BASE}/files/company_tickers.json", as_json=True)
    m = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    _cik_cache = (time.time(), m)
    return m


def earnings_filings(cik: int, since: str, meta: dict | None = None) -> list[dict]:
    """since(YYYY-MM-DD) 이후 Item 2.02가 들어간 8-K. meta를 주면 결산 월(fiscalYearEnd)을 채워 준다."""
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", as_json=True)
    if meta is not None:
        meta["fiscal_year_end"] = sub.get("fiscalYearEnd")
        meta["sic"] = sub.get("sic")
    rec = sub["filings"]["recent"]
    out = []
    for i, form in enumerate(rec["form"]):
        if form in ("8-K", "8-K/A") and "2.02" in (rec["items"][i] or "") and rec["filingDate"][i] >= since:
            out.append({"accession": rec["accessionNumber"][i], "filing_date": rec["filingDate"][i],
                        "report_date": rec["reportDate"][i] or None})
    return out


def exhibits(cik: int, accession: str) -> list[dict]:
    page = _get(f"{BASE}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.html")
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        link = re.search(r'href="([^"]+)"', row)
        if len(cells) >= 4 and cells[3].upper().startswith("EX-99") and link and link.group(1).lower().endswith((".htm", ".html", ".txt")):
            out.append({"type": cells[3].upper(), "description": cells[1], "url": BASE + link.group(1)})
    return out


def to_text(raw: str) -> str:
    """HTML → 문단을 살린 평문. 표 셀은 ' | '로."""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    t = re.sub(r"(?i)</(p|div|tr|li|h\d|br)\s*>|<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</t[dh]\s*>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip(" |") for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)[:MAX_CHARS]


def _store(conn: sqlite3.Connection, f: dict, filing: dict, ex: dict, text: str, entity_id: int | None) -> int | None:
    source_id = f"{f['ticker']}:{filing['accession']}:{ex['type']}"
    if conn.execute("SELECT 1 FROM raw_documents WHERE source_type='earnings_release' AND source_id=?", (source_id,)).fetchone() or \
            conn.execute("SELECT 1 FROM earnings_releases WHERE accession=? AND exhibit_type=?", (filing["accession"], ex["type"])).fetchone():
        return None     # 같은 공시(같은 회사의 다른 주식 종류 GOOG/GOOGL 등)를 두 번 저장하지 않는다
    kind = "CFO 코멘터리" if "cfo" in (ex["description"] + ex["url"]).lower() else "실적 보도자료"
    title = f"{f['company_name']} ({f['ticker']}) {kind} {filing['filing_date']} [{ex['type']}]"
    md = f"# {title}\n\n{text}"
    cur = conn.execute(
        "INSERT INTO raw_documents (source_type, source_id, title, url, published_at, raw_content, markdown, content_hash) "
        "VALUES ('earnings_release', ?, ?, ?, ?, ?, ?, ?)",
        (source_id, title, ex["url"], f"{filing['filing_date']}T21:00:00+00:00", text, md, hashlib.sha256(md.encode()).hexdigest()))
    doc_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO earnings_releases (doc_id, ticker, accession, filing_date, report_date, exhibit_type, description) "
                 "VALUES (?,?,?,?,?,?,?)", (doc_id, f["ticker"], filing["accession"], filing["filing_date"], filing["report_date"],
                                             ex["type"], ex["description"]))
    if entity_id:
        conn.execute("INSERT INTO entity_links (doc_id, entity_id, link_type, confidence) VALUES (?,?,'stock',1.0)", (doc_id, entity_id))
    return doc_id


def collect(conn: sqlite3.Connection, follows: list[dict], days_back: int = 400) -> dict:
    """대상 기업의 실적 8-K 첨부를 수집. 이미 저장한 첨부는 건너뛴다(멱등). 기본 400일 = 최근 4분기+."""
    since = (date.today() - timedelta(days=days_back)).isoformat()
    ciks = cik_map()
    stats = {"companies": 0, "filings": 0, "stored": 0, "no_cik": [], "same_cik": [], "errors": []}
    seen: set[int] = set()
    for f in follows:
        cik = ciks.get(f["ticker"].upper().replace(".", "-"))
        if not cik:
            stats["no_cik"].append(f["ticker"])
            continue
        if cik in seen:            # 한 회사의 여러 주식 종류(GOOG·GOOGL)는 한 번만
            stats["same_cik"].append(f["ticker"])
            continue
        seen.add(cik)
        stats["companies"] += 1
        try:
            known = {r[0] for r in conn.execute("SELECT DISTINCT accession FROM earnings_releases WHERE ticker=?", (f["ticker"],))}
            meta: dict = {}
            filings = earnings_filings(cik, since, meta)
            if meta.get("fiscal_year_end"):
                conn.execute("UPDATE transcript_follow SET fiscal_year_end=?, sic=COALESCE(?, sic) WHERE ticker=?",
                             (meta["fiscal_year_end"], meta.get("sic"), f["ticker"]))
            for filing in filings:
                if filing["accession"] in known:
                    continue
                stats["filings"] += 1
                for ex in exhibits(cik, filing["accession"]):
                    text = to_text(_get(ex["url"]))
                    if len(text) < 500:
                        continue
                    if _store(conn, f, filing, ex, text, f.get("entity_id")):
                        stats["stored"] += 1
                conn.commit()
        except SecNotConfigured:
            raise
        except Exception as e:  # noqa: BLE001 — 한 회사 실패가 전체를 막지 않게, 사유는 남긴다
            stats["errors"].append(f"{f['ticker']}: {type(e).__name__}: {str(e)[:80]}")
    return stats

"""Motley Fool 공개 컨콜 녹취록 수집 (D-218, docs/specs/transcript-momentum.md §수집).

AV 무료(하루 25회)로는 나스닥 100 컨콜을 따라갈 수 없어 사용자가 Fool을 택했다(2026-10-13).
- robots.txt는 일반 접근을 허용(특정 봇만 차단)하지만 이용약관은 자동 수집을 제한한다 → 개인 연구용으로
  **요청 간 3초, 하루 녹취록 40건 이하**, 실제 SEC 실적 발표가 있었는데 녹취록이 없는 분기만 가져온다.
- 주소의 회사명 부분과 날짜가 일정하지 않아(nvidia-nvda-q2-2027-earnings-call-transcript, …-earnings-transcript,
  8/26 발표 → 8/31 게시) 주소를 만들지 않고 종목 페이지(/quote/{거래소}/{티커}/)의 녹취록 목록에서 고른다:
  주소의 회계분기(q2-2027)가 우리가 계산한 라벨과 같으면 그것, 아니면 SEC 발표일 −2~+10일.
- 저장은 기존 `_store_call` 경로(raw_documents + transcripts + enrich + 인과 추출)를 그대로 탄다. 콜 날짜는 SEC 발표일.
"""
from __future__ import annotations

import html
import re
import time
from datetime import date

import requests

BASE = "https://www.fool.com"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
PAUSE = 3.0
DAILY_LIMIT = 40
LINK = re.compile(r"/earnings/call-transcripts/(\d{4})/(\d{2})/(\d{2})/([a-z0-9-]+?)/?(?=[\"\\])")
SLUG_Q = re.compile(r"-q([1-4])-(\d{4})-earnings")


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=30)
    time.sleep(PAUSE)
    return r


def transcript_links(ticker: str) -> list[dict]:
    """종목 페이지의 녹취록 목록. 나스닥 → 뉴욕 순으로 시도 — 나스닥 페이지가 200이어도 녹취록 링크가 없으면
    뉴욕도 본다(ORCL: /quote/nasdaq/orcl/이 빈 페이지로 200을 줘 '녹취록 없음'으로 끝났다)."""
    for exch in ("nasdaq", "nyse"):
        r = _get(f"{BASE}/quote/{exch}/{ticker.lower()}/")
        if r.status_code == 200 and "/earnings/call-transcripts/" in r.text:
            out, seen = [], set()
            for y, m, d, slug in LINK.findall(r.text):
                if slug in seen or f"-{ticker.lower()}-" not in f"-{slug}-":
                    continue
                seen.add(slug)
                q = SLUG_Q.search(slug)
                out.append({"url": f"{BASE}/earnings/call-transcripts/{y}/{m}/{d}/{slug}/", "date": f"{y}-{m}-{d}",
                            "label": (int(q.group(2)), int(q.group(1))) if q else None})
            return out
    return []


def pick(links: list[dict], fy: int, quarter: int, event_date: str) -> dict | None:
    """회계분기 라벨이 같은 것 우선, 없으면 SEC 발표일 −2~+10일 안에서 가장 가까운 것."""
    exact = [l for l in links if l["label"] == (fy, quarter)]
    if exact:
        return exact[0]
    ev = date.fromisoformat(event_date)
    near = [(abs((date.fromisoformat(l["date"]) - ev).days), l) for l in links
            if -2 <= (date.fromisoformat(l["date"]) - ev).days <= 10]
    return min(near, key=lambda x: x[0])[1] if near else None


def extract(page: str) -> str | None:
    """'Full Conference Call Transcript'부터 Fool 안내문 앞까지. 형태가 바뀌어 못 찾으면 None(조용히 엉뚱한 본문을 저장하지 않는다)."""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li)\s*>", "\n", t)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
    txt = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in txt.splitlines())
    txt = re.sub(r"\n{2,}", "\n\n", txt)
    start = txt.find("Full Conference Call Transcript")
    if start < 0:
        return None
    ends = [txt.find(m, start) for m in ("\nRead Next", "Premium Investing Services", "This article is a transcript")]
    end = min([i for i in ends if i > 0], default=len(txt))   # 본문 뒤 'Read Next'(관련 기사 목록)부터 버린다
    body = txt[start + len("Full Conference Call Transcript"):end].strip()
    # 진행자가 'Operator'가 아닌 콜도 있다(PLTR) — 화자 줄('이름:')이 충분한지로 본문을 확인한다
    speakers = len(re.findall(r"(?m)^[A-Z][\w .,'&\-]{1,60}:\s*$|^[A-Z][\w .,'&\-]{1,60}: ", body))
    return body if len(body) > 5000 and speakers >= 10 else None


class FoolProvider:
    """_store_call용 어댑터 — 미리 고른 (티커, 연, 분기) → 주소에서 본문을 가져온다."""
    name = "fool"

    def __init__(self, chosen: dict[tuple[str, int, int], dict]):
        self.chosen = chosen

    def fetch(self, ticker: str, year: int, quarter: int) -> dict | None:
        c = self.chosen.get((ticker, year, quarter))
        if not c:
            return None
        r = _get(c["url"])
        body = extract(r.text) if r.status_code == 200 else None
        return {"content": body, "date": c["event_date"]} if body else None


def collect(budget: int = DAILY_LIMIT, only: list[str] | None = None) -> dict:
    """SEC 실적 발표가 있었는데 녹취록이 없는 분기를 회사마다 최신순으로 라운드로빈."""
    from database import get_connection
    from pipeline.ops import retry_locked
    from pipeline.transcript import _bucket_map, _event_targets, _followed, _store_call
    companies = _followed(only)
    targets = _event_targets(companies)
    have = _bucket_map("SELECT ticker, fiscal_year, fiscal_period FROM transcripts")
    by = {f["ticker"]: f for f in companies}
    # 순번 = 회사의 '실제 발표 순서'(0 = 가장 최근 실적). 빠진 것만 모은 목록의 순번으로 돌면 최신 분기를 이미 받은
    # 회사가 바로 이전 분기를 받으러 가 주요 기업만 세로로 깊어진다(2026-10-13 사용자) — 전 종목 최신 → 전 종목 직전 순서.
    order = [f["ticker"] for f in companies if f["ticker"] in targets]   # _followed = 시가총액 큰 순
    missing = lambda t, q: (q["year"], f"Q{q['quarter']}") not in have.get(t, ())  # noqa: E731
    stats = {"stored": 0, "not_listed": 0, "parse_failed": 0, "pages": 0,
             "remaining": sum(missing(t, q) for t in order for q in targets[t])}
    links_cache: dict[str, list[dict]] = {}
    rank = 0
    while stats["stored"] + stats["parse_failed"] < budget and any(rank < len(targets[t]) for t in order):
        for ticker in order:
            qs = targets[ticker]
            if rank >= len(qs) or stats["stored"] + stats["parse_failed"] >= budget or not missing(ticker, qs[rank]):
                continue
            q = qs[rank]
            if ticker not in links_cache:
                links_cache[ticker] = transcript_links(ticker)
                stats["pages"] += 1
            c = pick(links_cache[ticker], q["year"], q["quarter"], q["date"])
            if not c:
                stats["not_listed"] += 1
                continue
            provider = FoolProvider({(ticker, q["year"], q["quarter"]): {**c, "event_date": q["date"]}})
            if retry_locked(lambda: _store_call(provider, by[ticker], q["year"], q["quarter"])):   # 이미 저장된 분기는 _store_call이 건너뛴다
                def _date():   # 콜 날짜 = SEC 실적 발표일(Fool 게시일은 며칠 늦을 수 있다)
                    conn = get_connection()
                    try:
                        conn.execute("UPDATE transcripts SET call_date=? WHERE ticker=? AND fiscal_year=? AND fiscal_period=?",
                                     (q["date"], ticker, q["year"], f"Q{q['quarter']}"))
                        conn.commit()
                    finally:
                        conn.close()
                retry_locked(_date)
                stats["stored"] += 1
                stats["remaining"] -= 1
            else:
                stats["parse_failed"] += 1
        rank += 1
    return stats

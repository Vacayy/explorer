"""포트폴리오 다가오는 이벤트 (docs/specs/portfolio-intelligence.md §4).

  확정 — 보유 종목의 DART 예고 공시(기업설명회·결산실적공시예고·주주총회소집) 본문에서 예정일을 뽑아 기존 `catalysts`에 저장
         (홈 캘린더·카탈리스트 화면에도 나온다)
  예상 — 확정 일정이 없을 때만: 작년 같은 분기 잠정실적 공시일 + 364일(같은 요일), 잠정실적 공시가 없는 회사는 분기보고서 제출 기한.
         추정치가 기존 일정에 섞이지 않게 `portfolio_event_estimates`에 따로 둔다
  해외 — 보유 종목이 속한 밸류체인의 대표 미국 기업 실적일(`transcript_calendar`, yfinance, 주 1회 갱신)
LLM 0. 매일 16:50 `pfclose`가 갱신한다.
"""
from __future__ import annotations

import html
import re
import sqlite3
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_event_estimates (
    stock_code  TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- earnings_est | report_deadline
    event_date  TEXT NOT NULL,
    title       TEXT NOT NULL,
    basis       TEXT,                   -- 추정 근거(작년 공시일 등)
    computed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, kind)
);
"""
KINDS = [("기업설명회", "ir", "기업설명회(IR)"), ("결산실적공시예고", "earnings_notice", "실적 발표 예정"),
         ("주주총회소집결의", "agm", "주주총회")]
DATE_RE = re.compile(r"(?:일시|예정일)[^0-9]{0,24}(\d{4})\s*[-.년]\s*(\d{1,2})\s*[-.월]\s*(\d{1,2})")
PURPOSE_RE = re.compile(r"개최목적\s*([^0-9][^.]{2,40}?)\s*(?:\d+\.|$)")
LOOKBACK_DAYS = 120
# 밸류체인 → 대표 미국 상장사(실적일이 국내 종목 흐름에 먼저 반영되는 곳). 체인은 portfolio_exposure가 판정한다.
CHAIN_TICKERS = {"반도체·전자부품": {"MU": "마이크론", "LRCX": "램리서치", "AMAT": "어플라이드머티리얼즈", "KLAC": "KLA",
                                  "ASML": "ASML", "TSM": "TSMC", "NVDA": "엔비디아", "TER": "테라다인"}}


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or "")))


def parse_event(text: str) -> tuple[str | None, str | None]:
    """공시 본문 → (예정일, 목적). 첫 '일시'·'예정일' 뒤 날짜."""
    m = DATE_RE.search(text)
    day = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    p = PURPOSE_RE.search(text)
    return day, (p.group(1).strip() if p else None)


def _windows(today: date, days: int, step: int = 30):
    """DART 목록은 기간이 길면 잘린다(2026-10-08 SK하이닉스 21개월 조회 0건) — 30일씩 나눠 조회."""
    end = today
    while (today - end).days < days:
        start = end - timedelta(days=step - 1)
        yield start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        end = start - timedelta(days=1)


def _dart():
    from services.dart_service import _corp_code_for_stock, _get_dart
    return _get_dart(), _corp_code_for_stock


def _filings(dart, corp: str, today: date, days: int) -> list[dict]:
    out = []
    for s, e in _windows(today, days):
        df = dart.list(corp, start=s, end=e)
        if df is not None and not df.empty:
            out += df.to_dict("records")
    return out


def collect_confirmed(conn: sqlite3.Connection, holdings: list[dict], today: date, dart=None, corp_of=None) -> int:
    """최근 120일 예고 공시에서 오늘 이후 예정일을 catalysts에 upsert. 이미 읽은 접수번호는 다시 열지 않는다."""
    if dart is None:
        dart, corp_of = _dart()
    n = 0
    for h in holdings:
        corp = corp_of(h["code"])
        if not corp:
            continue
        for f in _filings(dart, corp, today, LOOKBACK_DAYS):
            name = str(f.get("report_nm") or "")
            kind = next(((k, label) for key, k, label in KINDS if key in name), None)
            rcp = str(f.get("rcept_no") or "")
            if not kind or not rcp or conn.execute("SELECT 1 FROM catalysts WHERE description LIKE ?", (f"%{rcp}%",)).fetchone():
                continue
            day, purpose = parse_event(_clean(dart.document(rcp)))
            if not day or day < today.isoformat():
                continue
            title = f"{h['name']} {purpose or kind[1]}"
            conn.execute("DELETE FROM catalysts WHERE stock_code=? AND event_type=? AND event_date=?", (h["code"], kind[0], day))
            conn.execute("INSERT INTO catalysts (stock_code, corp_code, event_type, event_date, title, description) VALUES (?,?,?,?,?,?)",
                         (h["code"], corp, kind[0], day, title, f"DART {rcp} {name.strip()}"))
            n += 1
    conn.commit()
    return n


def _next_deadline(today: date) -> tuple[date, str]:
    """정기보고서 제출 기한: 분기·반기 45일, 사업보고서 90일."""
    y = today.year
    for d, label in [(date(y, 3, 31), "사업보고서"), (date(y, 5, 15), "1분기보고서"), (date(y, 8, 14), "반기보고서"),
                     (date(y, 11, 14), "3분기보고서"), (date(y + 1, 3, 31), "사업보고서")]:
        if d >= today:
            return d, label
    return date(y + 1, 3, 31), "사업보고서"


def estimate(conn: sqlite3.Connection, holdings: list[dict], today: date, dart=None, corp_of=None) -> int:
    """확정 실적 일정(IR·실적예고)이 없을 때만 예상치를 둔다."""
    if dart is None:
        dart, corp_of = _dart()
    n = 0
    for h in holdings:
        conn.execute("DELETE FROM portfolio_event_estimates WHERE stock_code=?", (h["code"],))
        confirmed = conn.execute("SELECT 1 FROM catalysts WHERE stock_code=? AND event_type IN ('ir','earnings_notice') "
                                 "AND event_date >= ? AND event_date <= ?",
                                 (h["code"], today.isoformat(), (today + timedelta(days=100)).isoformat())).fetchone()
        if confirmed:
            continue
        corp = corp_of(h["code"])
        last_year = [f for f in _filings(dart, corp, today - timedelta(days=265), 130) if "잠정)실적" in str(f.get("report_nm"))] if corp else []
        recent = [f for f in _filings(dart, corp, today, 45) if "잠정)실적" in str(f.get("report_nm"))] if corp else []
        dates = sorted(date.fromisoformat(f"{f['rcept_dt'][:4]}-{f['rcept_dt'][4:6]}-{f['rcept_dt'][6:]}") for f in last_year)
        ahead = [d for d in dates if d + timedelta(days=364) >= today]
        if ahead and not recent:
            filed = ahead[0]                                  # 1년 뒤가 오늘 이후인 것 중 가장 가까운 공시
            guess = filed + timedelta(days=364)
            if guess >= today:
                conn.execute("INSERT OR REPLACE INTO portfolio_event_estimates (stock_code, kind, event_date, title, basis) VALUES (?,?,?,?,?)",
                             (h["code"], "earnings_est", guess.isoformat(), f"{h['name']} 실적 발표(예상)", f"작년 같은 분기 잠정실적 {filed.isoformat()}"))
                n += 1
                continue
        if not last_year:
            d, label = _next_deadline(today)
            conn.execute("INSERT OR REPLACE INTO portfolio_event_estimates (stock_code, kind, event_date, title, basis) VALUES (?,?,?,?,?)",
                         (h["code"], "report_deadline", d.isoformat(), f"{h['name']} {label} 제출 기한", "잠정실적 공시 이력 없음 — 법정 기한"))
            n += 1
    conn.commit()
    return n


def chain_tickers(chains: set[str]) -> dict[str, str]:
    out = {}
    for c in chains:
        out.update(CHAIN_TICKERS.get(c, {}))
    return out


def refresh_us(tickers: list[str]) -> int:
    from pipeline.transcript import refresh_calendar
    return refresh_calendar(tickers, max_age_hours=24 * 7) if tickers else 0


def upcoming(conn: sqlite3.Connection, holdings: list[dict], chains: set[str], today: date, days: int = 45) -> list[dict]:
    """다가오는 이벤트 — 확정·예상·해외를 날짜순으로. 금액 없음."""
    end = (today + timedelta(days=days)).isoformat()
    codes = [h["code"] for h in holdings]
    names = {h["code"]: h["name"] for h in holdings}
    items = []
    if codes:
        q = ",".join("?" * len(codes))
        for r in conn.execute(f"SELECT stock_code, event_type, event_date, title, description FROM catalysts WHERE stock_code IN ({q}) "
                              f"AND event_date >= ? AND event_date <= ? ORDER BY event_date", (*codes, today.isoformat(), end)):
            rcp = re.search(r"DART (\d{14})", r["description"] or "")
            items.append({"date": r["event_date"], "kind": r["event_type"], "title": r["title"], "code": r["stock_code"],
                          "name": names.get(r["stock_code"]), "estimated": False,
                          "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp.group(1)}" if rcp else None, "basis": None})
        for r in conn.execute(f"SELECT * FROM portfolio_event_estimates WHERE stock_code IN ({q}) AND event_date >= ? AND event_date <= ?",
                              (*codes, today.isoformat(), end)):
            items.append({"date": r["event_date"], "kind": r["kind"], "title": r["title"], "code": r["stock_code"],
                          "name": names.get(r["stock_code"]), "estimated": True, "url": None, "basis": r["basis"]})
    us = chain_tickers(chains)
    if us:
        q = ",".join("?" * len(us))
        for r in conn.execute(f"SELECT ticker, next_report_date FROM transcript_calendar WHERE ticker IN ({q}) "
                              f"AND next_report_date >= ? AND next_report_date <= ?", (*us, today.isoformat(), end)):
            tk, name = r["ticker"], us[r["ticker"]]
            label = name if name == tk else f"{name}({tk})"
            items.append({"date": r["next_report_date"], "kind": "us_earnings", "title": f"{label} 실적 발표",
                          "code": None, "name": None, "estimated": False, "url": None, "basis": "yfinance 실적 일정"})
    return sorted(items, key=lambda i: (i["date"], i["kind"]))

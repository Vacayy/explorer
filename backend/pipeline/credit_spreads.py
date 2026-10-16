"""회사채 스프레드 — AI 설비투자 기업의 신용 긴장 (D-230, docs/specs/credit-spreads.md). LLM 0.

채권 수익률은 공개 저장소 밖 로컬 어댑터(`local_sources.credit_source`, git 제외)가 제공한다. 어댑터가 없으면
configured=False로 빈 상태를 돌려주고, 국채 곡선(FRED 공식 CSV)·계산·화면은 그대로다. 받은 값은 로컬 DB에만.

어댑터 계약(Source):
  resolve(company) -> {symbol, description, coupon, maturity, rating_sp, rating_moodys, outstanding, source, value_kind} | None
  history(symbol, bars) -> [(YYYY-MM-DD, value)]  # value_kind=yield면 만기 수익률(%), price면 가격(액면 100)
"""
from __future__ import annotations

import importlib
import math
import sqlite3
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS credit_bonds (
    ticker       TEXT PRIMARY KEY,
    symbol       TEXT NOT NULL,
    description  TEXT,
    coupon       REAL,
    maturity     TEXT,
    rating_sp    TEXT,
    rating_moodys TEXT,
    outstanding  REAL,
    source       TEXT,              -- TRACE | 유럽 거래소
    value_kind   TEXT,              -- yield | price
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS credit_quotes (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    ytm     REAL NOT NULL,          -- 만기 수익률(%)
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS treasury_curve (
    date    TEXT NOT NULL,
    tenor   REAL NOT NULL,          -- 만기(년)
    yield   REAL NOT NULL,          -- %
    PRIMARY KEY (date, tenor)
);
"""

SOURCE_MODULE = "local_sources.credit_source"
RECOVERY = 0.4                       # 부도확률 근사의 회수율
PD_YEARS = 5
RESOLVE_EVERY_DAYS = 7
TREASURY = {"DGS3MO": 0.25, "DGS6MO": 0.5, "DGS1": 1, "DGS2": 2, "DGS3": 3, "DGS5": 5, "DGS7": 7, "DGS10": 10, "DGS20": 20, "DGS30": 30}
HY_SP = ("BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D")

GROUPS = [
    ("hyperscaler", "하이퍼스케일러"),
    ("ai_cloud", "AI 클라우드·데이터센터 개발"),
    ("semis", "반도체·하드웨어"),
    ("dc_reit", "데이터센터 리츠·인프라"),
    ("power", "전력"),
    ("funding", "자금줄 (사모신용·투자자)"),
]
# (티커, 화면 이름, 발행사 검색어, 묶음)
COMPANIES: list[dict] = [{"ticker": t, "name": n, "issuer": i, "group": g} for t, n, i, g in [
    ("ORCL", "오라클", "Oracle Corporation", "hyperscaler"),
    ("META", "메타", "Meta Platforms", "hyperscaler"),
    ("AMZN", "아마존", "Amazon.com", "hyperscaler"),
    ("MSFT", "마이크로소프트", "Microsoft Corporation", "hyperscaler"),
    ("GOOGL", "알파벳", "Alphabet Inc.", "hyperscaler"),
    ("AAPL", "애플", "Apple Inc.", "hyperscaler"),
    ("CRWV", "코어위브", "CoreWeave", "ai_cloud"),
    ("CORZ", "코어 사이언티픽", "Core Scientific", "ai_cloud"),
    ("APLD", "어플라이드 디지털", "Applied Digital", "ai_cloud"),
    ("CIFR", "사이퍼", "Cipher Compute", "ai_cloud"),
    ("WULF", "테라울프", "TeraWulf", "ai_cloud"),
    ("Beignet", "메타 하이페리온 SPV", "Beignet Investor", "ai_cloud"),
    ("HUT", "헛에이트", "Hut 8", "ai_cloud"),
    ("STX", "씨게이트", "Seagate HDD", "semis"),
    ("HPE", "HPE", "Hewlett Packard Enterprise", "semis"),
    ("MU", "마이크론", "Micron Technology", "semis"),
    ("AVGO", "브로드컴", "Broadcom Inc.", "semis"),
    ("DELL", "델", "Dell International", "semis"),
    ("INTC", "인텔", "Intel Corporation", "semis"),
    ("AMD", "AMD", "Advanced Micro Devices", "semis"),
    ("NVDA", "엔비디아", "NVIDIA Corporation", "semis"),
    ("QCOM", "퀄컴", "QUALCOMM", "semis"),
    ("TSM", "TSMC", "TSMC Arizona", "semis"),
    ("IRM", "아이언 마운틴", "Iron Mountain", "dc_reit"),
    ("EQIX", "에퀴닉스", "Equinix", "dc_reit"),
    ("DLR", "디지털 리얼티", "Digital Realty Trust", "dc_reit"),
    ("TLN", "탈렌", "Talen Energy", "power"),
    ("NRG", "NRG", "NRG Energy", "power"),
    ("VST", "비스트라", "Vistra Operations", "power"),
    ("CEG", "컨스텔레이션", "Constellation Energy Generation", "power"),
    ("SoftBank", "소프트뱅크그룹", "SoftBank Group", "funding"),
    ("OTF", "블루아울 테크놀로지 파이낸스", "Blue Owl Technology Finance", "funding"),
    ("OBDC", "블루아울 캐피탈", "Blue Owl Capital Corporation", "funding"),
    ("ARCC", "아레스 캐피탈", "Ares Capital Corporation", "funding"),
]]
BY_TICKER = {c["ticker"]: c for c in COMPANIES}


class NotConfigured(RuntimeError):
    """로컬 데이터 원천 어댑터가 없다."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def source():
    try:
        return importlib.import_module(SOURCE_MODULE)
    except ImportError:
        return None


# ── 계산 (순수) ───────────────────────────────────────────────────────────────

def interpolate(curve: list[tuple[float, float]], years: float) -> float | None:
    """[(만기, 금리)] 정렬된 곡선에서 선형 보간. 범위 밖은 끝값."""
    if not curve:
        return None
    tenors = [t for t, _ in curve]
    if years <= tenors[0]:
        return curve[0][1]
    if years >= tenors[-1]:
        return curve[-1][1]
    i = bisect_right(tenors, years)
    (t0, y0), (t1, y1) = curve[i - 1], curve[i]
    return y0 + (y1 - y0) * (years - t0) / (t1 - t0)


def ytm_from_price(price: float, coupon: float, settle: date, maturity: date, freq: int = 2) -> float | None:
    """가격(액면 100) → 만기 수익률(%) — 고정 이표·반기 가정, 이분법. 경과 이자는 무시(근사)."""
    years = (maturity - settle).days / 365.25
    if years <= 0 or price <= 0:
        return None
    n = years * freq
    c = coupon / freq

    def pv(y):
        r = y / 100 / freq
        k = math.ceil(n)
        first = n - (k - 1)                      # 첫 이표까지 남은 기간(주기 단위)
        return sum(c / (1 + r) ** (first + j) for j in range(k)) + 100 / (1 + r) ** n

    lo, hi = -5.0, 60.0
    if not pv(hi) <= price <= pv(lo):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pv(mid) > price else (lo, mid)
    return round((lo + hi) / 2, 4)


def default_probability(spread_bp: float | None) -> float | None:
    """위험중립 근사 5년 누적 부도확률(%) = 1 − exp(−s/(1−R)·T)."""
    if spread_bp is None:
        return None
    return round(max(0.0, 1 - math.exp(-(spread_bp / 10000) / (1 - RECOVERY) * PD_YEARS)) * 100, 1)   # 음수 스프레드는 0


def is_hy(rating_sp: str | None, rating_moodys: str | None) -> bool:
    return (rating_sp in HY_SP) or bool(rating_moodys and rating_moodys[0] in "BC" and not rating_moodys.startswith("Baa"))


# ── 저장소 ───────────────────────────────────────────────────────────────────

def _curves(conn: sqlite3.Connection, since: str) -> tuple[list[str], dict[str, list[tuple[float, float]]]]:
    by_day: dict[str, list[tuple[float, float]]] = {}
    for r in conn.execute("SELECT date, tenor, yield FROM treasury_curve WHERE date >= ? ORDER BY date, tenor", (since,)):
        by_day.setdefault(r[0], []).append((r[1], r[2]))
    days = sorted(by_day)
    return days, by_day


def _curve_on(days: list[str], by_day: dict, day: str):
    i = bisect_right(days, day)
    return by_day[days[i - 1]] if i else None


def spread_series(conn: sqlite3.Connection, ticker: str, since: str) -> list[dict]:
    """날짜별 {date, ytm, treasury, spread_bp}. 국채는 그날(없으면 직전) 곡선을 그날의 잔존 만기로 보간."""
    bond = conn.execute("SELECT symbol, maturity FROM credit_bonds WHERE ticker=?", (ticker,)).fetchone()
    if not bond or not bond[1]:
        return []
    days, by_day = _curves(conn, (date.fromisoformat(since) - timedelta(days=10)).isoformat())
    maturity = date.fromisoformat(bond[1])
    out = []
    for d, ytm in conn.execute("SELECT date, ytm FROM credit_quotes WHERE symbol=? AND date >= ? ORDER BY date", (bond[0], since)):
        curve = _curve_on(days, by_day, d)
        tsy = interpolate(curve, (maturity - date.fromisoformat(d)).days / 365.25) if curve else None
        out.append({"date": d, "ytm": round(ytm, 4), "treasury": round(tsy, 4) if tsy is not None else None,
                    "spread_bp": round((ytm - tsy) * 100, 1) if tsy is not None else None})
    return out


def _before(series: list[dict], day: str) -> float | None:
    vals = [p["spread_bp"] for p in series if p["date"] <= day and p["spread_bp"] is not None]
    return vals[-1] if vals else None


def table(conn: sqlite3.Connection) -> dict:
    ensure_schema(conn)
    since = (date.today() - timedelta(days=400)).isoformat()
    rows, as_of = [], None
    bonds = {r[0]: r for r in conn.execute("SELECT ticker, description, rating_sp, rating_moodys, source FROM credit_bonds")}
    for c in COMPANIES:
        b = bonds.get(c["ticker"])
        series = spread_series(conn, c["ticker"], since) if b else []
        last = series[-1] if series else None
        row = {"ticker": c["ticker"], "name": c["name"], "group": c["group"], "bond": b[1] if b else None,
               "rating": (b[2] or b[3]) if b else None, "hy": is_hy(b[2], b[3]) if b else False, "source": b[4] if b else None,
               "ytm": None, "treasury": None, "spread_bp": None, "chg_1m": None, "chg_3m": None, "chg_1y": None, "pd_pct": None, "last_date": None}
        if last and last["spread_bp"] is not None:
            d0 = date.fromisoformat(last["date"])
            change = lambda days: (lambda prev: round(last["spread_bp"] - prev) if prev is not None and series[0]["date"] <= (d0 - timedelta(days=days)).isoformat() else None)(  # noqa: E731
                _before(series, (d0 - timedelta(days=days)).isoformat()))
            row.update(ytm=last["ytm"], treasury=last["treasury"], spread_bp=round(last["spread_bp"]), last_date=last["date"],
                       chg_1m=change(30), chg_3m=change(91), chg_1y=change(365), pd_pct=default_probability(last["spread_bp"]))
            as_of = max(as_of or last["date"], last["date"])
        rows.append(row)
    return {"configured": source() is not None, "as_of": as_of, "groups": [{"key": k, "label": v} for k, v in GROUPS], "rows": rows}


def history(conn: sqlite3.Connection, tickers: list[str], days: int = 1000) -> dict:
    """선택 회사들의 날짜별 수익률·스프레드와 그 회사들의 국채(같은 만기) 평균."""
    ensure_schema(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    per = {t: {p["date"]: p for p in spread_series(conn, t, since)} for t in tickers if t in BY_TICKER}
    dates = sorted({d for s in per.values() for d in s})
    points = []
    for d in dates:
        row = {"date": d}
        tsy = []
        for t, s in per.items():
            p = s.get(d)
            if p:
                row[f"{t}_ytm"], row[f"{t}_spread"] = p["ytm"], p["spread_bp"]
                if p["treasury"] is not None:
                    tsy.append(p["treasury"])
        row["treasury"] = round(sum(tsy) / len(tsy), 4) if tsy else None
        points.append(row)
    return {"tickers": list(per), "points": points}


# ── 수집 ────────────────────────────────────────────────────────────────────

def update_treasury(conn: sqlite3.Connection, days: int) -> int:
    from pipeline.macro import _public_fred_history
    n = 0
    for series_id, tenor in TREASURY.items():
        rows = _public_fred_history(series_id, days)
        conn.executemany("INSERT OR REPLACE INTO treasury_curve (date, tenor, yield) VALUES (?, ?, ?)", [(d, tenor, v) for d, v in rows])
        n += len(rows)
    conn.commit()
    return n


def collect(conn: sqlite3.Connection, src=None, tickers: list[str] | None = None) -> dict:
    """국채 곡선 → 대표 채권(주 1회 재선정) → 이력(첫 수집 전체, 이후 최근 30봉) → 저장. 실패한 회사는 건너뛴다."""
    ensure_schema(conn)
    src = src or source()
    if src is None:
        raise NotConfigured("로컬 데이터 원천 어댑터(local_sources.credit_source)가 없습니다.")
    first_curve = not conn.execute("SELECT 1 FROM treasury_curve LIMIT 1").fetchone()
    result = {"treasury_rows": update_treasury(conn, 3000 if first_curve else 30), "ok": 0, "failed": [], "resolved": 0}
    stale = (datetime.now(timezone.utc) - timedelta(days=RESOLVE_EVERY_DAYS)).isoformat()
    for c in COMPANIES:
        if tickers and c["ticker"] not in tickers:
            continue
        try:
            bond = conn.execute("SELECT * FROM credit_bonds WHERE ticker=?", (c["ticker"],)).fetchone()
            if not bond or (bond["updated_at"] or "") < stale:
                info = src.resolve(c)
                if not info:
                    conn.execute("DELETE FROM credit_bonds WHERE ticker=?", (c["ticker"],))   # 예전에 잘못 고른 채권을 남기지 않는다
                    conn.commit()
                    result["failed"].append(f"{c['ticker']}: 대표 채권 없음")
                    continue
                conn.execute("INSERT OR REPLACE INTO credit_bonds (ticker, symbol, description, coupon, maturity, rating_sp, rating_moodys, "
                             "outstanding, source, value_kind, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (c["ticker"], info["symbol"], info.get("description"), info.get("coupon"), info.get("maturity"),
                              info.get("rating_sp"), info.get("rating_moodys"), info.get("outstanding"), info.get("source"),
                              info.get("value_kind") or "yield", datetime.now(timezone.utc).isoformat()))
                conn.commit()
                result["resolved"] += 1
                bond = conn.execute("SELECT * FROM credit_bonds WHERE ticker=?", (c["ticker"],)).fetchone()
            have = conn.execute("SELECT count(*) FROM credit_quotes WHERE symbol=?", (bond["symbol"],)).fetchone()[0]
            bars = src.history(bond["symbol"], 30 if have > 20 else 2000)
            rows = []
            for d, v in bars:
                ytm = v if bond["value_kind"] != "price" else (
                    ytm_from_price(v, bond["coupon"], date.fromisoformat(d), date.fromisoformat(bond["maturity"]))
                    if bond["coupon"] is not None and bond["maturity"] else None)
                if ytm is not None and 0 < ytm < 60:
                    rows.append((bond["symbol"], d, ytm))
            conn.executemany("INSERT OR REPLACE INTO credit_quotes (symbol, date, ytm) VALUES (?, ?, ?)", rows)
            conn.commit()
            result["ok"] += 1
        except Exception as e:  # noqa: BLE001 — 한 회사 실패가 전체를 막지 않는다
            result["failed"].append(f"{c['ticker']}: {type(e).__name__}: {str(e)[:80]}")
        time.sleep(1.0)
    return result

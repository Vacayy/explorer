"""개인 투자 열기 — 빚투·대기자금·거래 열기 (D-231, docs/specs/retail-heat.md). LLM 0.

절대 잔액이 아니라 변화 속도와 시장 규모 대비 비율을 보고, 증가 속도를 과거 5년 분포의 백분위로 읽는다.
원천: 금융투자협회 통계(키 불필요) + 한국거래소(로그인, .env KRX_ID·KRX_PW — 없으면 그 열만 비운다).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from bisect import bisect_left
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS retail_flows (
    date          TEXT PRIMARY KEY,   -- YYYY-MM-DD 영업일
    deposits      REAL,               -- 투자자예탁금(원)
    receivables   REAL,               -- 위탁매매 미수금
    forced_sales  REAL,               -- 미수금 대비 실제 반대매매 금액
    forced_ratio  REAL,               -- 반대매매 비중(%)
    credit_total  REAL,               -- 신용거래융자 전체
    credit_kospi  REAL,
    credit_kosdaq REAL,
    kospi_close   REAL,
    kospi_value   REAL,               -- 거래대금
    kosdaq_value  REAL,
    kospi_cap     REAL,               -- 시가총액
    kosdaq_cap    REAL,
    indiv_buy     REAL,               -- 한국거래소: 유가+코스닥 개인 매수 거래대금
    indiv_sell    REAL,
    total_buy     REAL,
    total_sell    REAL,
    lev_value     REAL,               -- 레버리지 ETF 대표 종목 거래대금 합
    inv_value     REAL,               -- 인버스 ETF 대표 종목 거래대금 합
    active_accounts REAL              -- 주식거래활동계좌(경로 미확보)
);
CREATE TABLE IF NOT EXISTS retail_snapshots (
    episode   TEXT PRIMARY KEY,
    date      TEXT,
    metrics_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

KOFIA_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
MILLION = 1_000_000
WINDOW = 20                      # 영업일
PCTILE_DAYS = 1250               # 약 5년
MIN_PCTILE_DAYS = 500            # 이력이 2년 미만이면 백분위를 비운다
# 협회 통계 → 열 (TMPV 번호, 백만원이면 원으로 환산)
KOFIA_SERIES = {
    "STATSCU0100000060BO": {"TMPV2": ("deposits", MILLION), "TMPV5": ("receivables", MILLION),
                            "TMPV6": ("forced_sales", MILLION), "TMPV7": ("forced_ratio", 1)},
    "STATSCU0100000070BO": {"TMPV2": ("credit_total", MILLION), "TMPV3": ("credit_kospi", MILLION), "TMPV4": ("credit_kosdaq", MILLION)},
    "STATSCU0100000020BO": {"TMPV2": ("kospi_close", 1), "TMPV4": ("kospi_value", MILLION), "TMPV5": ("kospi_cap", MILLION)},
    "STATSCU0100000030BO": {"TMPV4": ("kosdaq_value", MILLION), "TMPV5": ("kosdaq_cap", MILLION)},
}
LEVERAGED_ETFS = ["122630", "233740"]            # KODEX 레버리지 · KODEX 코스닥150레버리지
INVERSE_ETFS = ["252670", "114800", "251340"]    # KODEX 200선물인버스2X · KODEX 인버스 · KODEX 코스닥150선물인버스

EPISODES = [  # (키, 이름, 시작, 끝) — 구간 안에서 신용융자 증가율 백분위가 가장 높았던 날을 스냅샷
    ("2007", "2007 펀드·중국 열풍", "2007-04-01", "2007-11-30"),
    ("2011", "2011 차화정", "2011-01-01", "2011-08-05"),
    ("2015", "2015 코스닥·바이오", "2015-02-01", "2015-08-10"),
    ("2018", "2018.1 바이오·남북경협", "2017-10-01", "2018-06-30"),
    ("2021", "2020~21 동학개미", "2020-06-01", "2021-07-31"),
    ("2023", "2023 2차전지", "2023-02-01", "2023-08-31"),
]

REGIMES = {
    "deleveraging": "레버리지 축소",
    "leverage_led": "레버리지 의존 상승",
    "churn": "회전 과열(기존 투자자 매매)",
    "broad_inflow": "폭넓은 개인 자금 유입",
    "neutral": "중립",
}


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


# ── 수집 ────────────────────────────────────────────────────────────────────

def kofia(obj: str, start: str, end: str, tries: int = 3) -> list[dict]:
    """협회 통계 한 구간. 응답이 가끔 잘려 오므로 재시도."""
    body = {"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D", "tmpV45": start, "tmpV46": end, "OBJ_NM": obj}}
    for k in range(tries):
        try:
            req = urllib.request.Request(KOFIA_URL, json.dumps(body).encode(), {
                "Content-Type": "application/json; charset=UTF-8", "User-Agent": "Mozilla/5.0", "Referer": "https://freesis.kofia.or.kr/"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r).get("ds1") or []
        except (ValueError, OSError):
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))
    return []


def _upsert(conn, rows: dict[str, dict]) -> int:
    for day, cols in rows.items():
        conn.execute("INSERT OR IGNORE INTO retail_flows (date) VALUES (?)", (day,))
        sets = ", ".join(f"{c}=?" for c in cols)
        conn.execute(f"UPDATE retail_flows SET {sets} WHERE date=?", (*cols.values(), day))
    conn.commit()
    return len(rows)


def collect_kofia(conn, start: date, end: date) -> int:
    rows: dict[str, dict] = {}
    chunks, cur = [], date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    while cur <= end:      # 분기 단위로 끊는다 — 응답이 약 32KB에서 잘려 1년치(30KB+)는 자주 깨진다
        nxt = date(cur.year + (cur.month + 3 > 12), (cur.month + 2) % 12 + 1, 1)
        chunks.append((max(start, cur), min(end, nxt - timedelta(days=1))))
        cur = nxt
    for s, e in chunks:
        for obj, cols in KOFIA_SERIES.items():
            for rec in kofia(obj, s.strftime("%Y%m%d"), e.strftime("%Y%m%d")):
                d = rec.get("TMPV1", "")
                if len(d) != 8 or not d.isdigit():
                    continue
                day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                for key, (col, mult) in cols.items():
                    v = rec.get(key)
                    if isinstance(v, (int, float)):
                        rows.setdefault(day, {})[col] = float(v) * mult
            time.sleep(0.3)
    return _upsert(conn, rows)


class KrxLoginError(RuntimeError):
    """한국거래소 로그인 실패 — 협회 수집은 저장하고 이 부분만 오류로 드러낸다."""


def krx_configured() -> bool:
    return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))


def _krx_logged_in() -> bool:
    from pykrx.website.comm import auth
    return auth._auth_session is not None


def collect_krx(conn, start: date, end: date) -> int:
    """개인·전체 매수/매도 거래대금(유가+코스닥)과 레버리지·인버스 ETF 대표 종목 거래대금. 로그인 필요."""
    if not krx_configured():
        return 0
    # 로그인은 한 번만 — pykrx가 import 때 .env 계정으로 이미 로그인하므로(중복 로그인 확인 포함) 그 세션을 쓴다.
    # 실패 시 pykrx는 호출마다 재로그인을 시도해 실패가 쌓이면 계정이 잠길 수 있어 여기서 멈춘다
    if not _krx_logged_in():
        raise KrxLoginError("한국거래소 로그인 실패 — .env KRX_ID·KRX_PW 확인(정보데이터시스템 아이디). 연속 실패를 막으려 이번 수집은 건너뜀")
    from pykrx import stock
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    rows: dict[str, dict] = {}
    for side, col_i, col_t in (("매수", "indiv_buy", "total_buy"), ("매도", "indiv_sell", "total_sell")):
        for market in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_trading_value_by_date(s, e, market, on=side)
            for idx, r in df.iterrows():
                day = idx.date().isoformat()
                cell = rows.setdefault(day, {})
                cell[col_i] = cell.get(col_i, 0.0) + float(r.get("개인", 0) or 0)
                cell[col_t] = cell.get(col_t, 0.0) + float(r.get("전체", 0) or r.drop(labels=["전체"], errors="ignore").sum())
            time.sleep(1)
    for tickers, col in ((LEVERAGED_ETFS, "lev_value"), (INVERSE_ETFS, "inv_value")):
        for t in tickers:
            df = stock.get_etf_ohlcv_by_date(s, e, t)
            for idx, r in df.iterrows():
                cell = rows.setdefault(idx.date().isoformat(), {})
                cell[col] = cell.get(col, 0.0) + float(r.get("거래대금", 0) or 0)
            time.sleep(1)
    return _upsert(conn, rows)


def collect(conn, full: bool = False) -> dict:
    ensure_schema(conn)
    have = conn.execute("SELECT min(date), max(date) FROM retail_flows WHERE credit_total IS NOT NULL").fetchone()
    first = full or not have[0]
    end = date.today()
    start = date(1999, 1, 1) if first else date.fromisoformat(have[1]) - timedelta(days=30)
    result = {"kofia_rows": collect_kofia(conn, start, end)}
    if krx_configured():
        krx_have = conn.execute("SELECT max(date) FROM retail_flows WHERE indiv_buy IS NOT NULL").fetchone()[0]
        krx_start = date.fromisoformat(krx_have) - timedelta(days=30) if krx_have and not full else end - timedelta(days=365 * 6)
        try:
            result["krx_rows"] = collect_krx(conn, krx_start, end)
            if not result["krx_rows"]:
                result["krx_error"] = "한국거래소 응답 0행"
        except KrxLoginError as e:
            result["krx_error"] = str(e)
    else:
        result["krx"] = "계정 없음(.env KRX_ID·KRX_PW)"
    result["snapshots"] = save_snapshots(conn)
    return result


# ── 계산 (순수) ─────────────────────────────────────────────────────────────

def percentile_rank(history: list[float], value: float | None) -> float | None:
    """value가 history 분포에서 몇 백분위인가(0~100). history는 정렬 불필요."""
    if value is None or len(history) < MIN_PCTILE_DAYS:
        return None
    ordered = sorted(history)
    return round(bisect_left(ordered, value) / len(ordered) * 100, 1)


def _num(v):
    return v if isinstance(v, (int, float)) else None


def series(conn) -> list[dict]:
    """날짜순 원시 행 + 파생 지표."""
    ensure_schema(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM retail_flows ORDER BY date")]
    out = []
    for i, r in enumerate(rows):
        prev = rows[i - WINDOW] if i >= WINDOW else None
        window = rows[max(0, i - WINDOW + 1): i + 1]
        before = rows[max(0, i - 2 * WINDOW + 1): max(0, i - WINDOW + 1)]

        def growth(col):
            a, b = _num(r.get(col)), _num(prev.get(col)) if prev else None
            return (a - b) / b if a is not None and b else None

        def avg(rs, fn):
            vals = [fn(x) for x in rs]
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None

        value = lambda x: (_num(x.get("kospi_value")) or 0) + (_num(x.get("kosdaq_value")) or 0) or None  # noqa: E731
        cap = lambda x: (_num(x.get("kospi_cap")) or 0) + (_num(x.get("kosdaq_cap")) or 0) or None  # noqa: E731
        v_now, v_before = avg(window, value), avg(before, value)
        total_value_20 = sum(v for v in (value(x) for x in window) if v) if len(window) == WINDOW else None
        cap_avg = avg(window, cap)
        lev = sum(_num(x.get("lev_value")) or 0 for x in window) if any(_num(x.get("lev_value")) for x in window) else None
        inv = sum(_num(x.get("inv_value")) or 0 for x in window) if any(_num(x.get("inv_value")) for x in window) else None
        ib, isl, tb, ts = (sum(_num(x.get(c)) or 0 for x in window) for c in ("indiv_buy", "indiv_sell", "total_buy", "total_sell"))
        has_krx = any(_num(x.get("indiv_buy")) for x in window)
        out.append({
            "date": r["date"], "credit_total": r.get("credit_total"), "deposits": r.get("deposits"), "kospi_close": r.get("kospi_close"),
            "value": value(r), "forced_sales": r.get("forced_sales"),
            "credit_growth": growth("credit_total"), "deposit_growth": growth("deposits"), "kospi_return": growth("kospi_close"),
            "value_growth": (v_now / v_before - 1) if v_now and v_before and len(before) == WINDOW else None,
            "leverage": (r["credit_total"] / cap(r)) if r.get("credit_total") and cap(r) else None,
            "turnover": (total_value_20 / cap_avg) if total_value_20 and cap_avg else None,
            "indiv_share": ((ib + isl) / (tb + ts)) if has_krx and (tb + ts) else None,
            "indiv_net_20": (ib - isl) if has_krx else None,
            "lev_pref": (lev / total_value_20) if lev is not None and total_value_20 else None,
            "inv_pref": (inv / total_value_20) if inv is not None and total_value_20 else None,
            "forced_20": sum(_num(x.get("forced_sales")) or 0 for x in window) if len(window) == WINDOW else None,
            "accounts_growth": growth("active_accounts"),
        })
    return out


PCTILE_KEYS = ["credit_growth", "deposit_growth", "value_growth", "leverage", "turnover", "indiv_share", "indiv_net_20",
               "lev_pref", "inv_pref", "forced_20", "accounts_growth"]


def with_percentiles(points: list[dict], keys=PCTILE_KEYS) -> list[dict]:
    """각 날의 지표를 그날 이전 5년(약 1,250영업일) 분포의 백분위로 — 미래 정보 없음.

    정렬된 창을 유지하며 한 칸씩 넣고 뺀다(날마다 다시 정렬하면 27년 × 11지표에서 느리다).
    """
    from bisect import insort
    from collections import deque
    order: dict[str, deque] = {k: deque() for k in keys}
    ranked: dict[str, list[float]] = {k: [] for k in keys}
    out = []
    for p in points:
        q = dict(p)
        for k in keys:
            v, window = p.get(k), ranked[k]
            q[f"{k}_pct"] = round(bisect_left(window, v) / len(window) * 100, 1) if v is not None and len(window) >= MIN_PCTILE_DAYS else None
            if v is not None:
                order[k].append(v)
                insort(window, v)
                if len(order[k]) > PCTILE_DAYS:
                    old = order[k].popleft()
                    del window[bisect_left(window, old)]
        out.append(q)
    return out


def classify(p: dict) -> dict:
    """국면 판정(결정적 규칙) + 근거."""
    cg, cgp = p.get("credit_growth"), p.get("credit_growth_pct")
    vg, vgp = p.get("value_growth"), p.get("value_growth_pct")
    dgp, agp, ret = p.get("deposit_growth_pct"), p.get("accounts_growth_pct"), p.get("kospi_return")
    pct = lambda v: "-" if v is None else f"{v:.0f}"   # noqa: E731
    rate = lambda v: "-" if v is None else f"{v * 100:+.1f}%"   # noqa: E731
    if ret is not None and cg is not None and cgp is not None and ret <= -0.05 and cg < 0 and cgp <= 15:
        return {"key": "deleveraging", "label": REGIMES["deleveraging"],
                "reasons": [f"KOSPI 20일 {rate(ret)} (≤ −5%)", f"신용융자 20일 {rate(cg)}, 5년 백분위 {pct(cgp)} (≤ 15)",
                            f"반대매매 20일 합 백분위 {pct(p.get('forced_20_pct'))} — 반대매매 통계 확인"]}
    if cgp is not None and dgp is not None and cg is not None and vg is not None and cgp >= 70 and cg > vg and dgp < 60:
        return {"key": "leverage_led", "label": REGIMES["leverage_led"],
                "reasons": [f"신용융자 증가율 백분위 {pct(cgp)} (≥ 70)", f"신용융자 {rate(cg)} > 거래대금 {rate(vg)}", f"예탁금 증가율 백분위 {pct(dgp)} (< 60)"]}
    if vgp is not None and dgp is not None and vgp >= 80 and dgp < 50 and (agp is None or agp < 50):
        return {"key": "churn", "label": REGIMES["churn"],
                "reasons": [f"거래대금 증가율 백분위 {pct(vgp)} (≥ 80)", f"예탁금 증가율 백분위 {pct(dgp)} (< 50, 신규 참여 둔화)"]
                + ([f"활동계좌 증가율 백분위 {pct(agp)} (< 50)"] if agp is not None else [])}
    if all(x is not None and x >= 60 for x in (dgp, vgp, cgp)):
        return {"key": "broad_inflow", "label": REGIMES["broad_inflow"],
                "reasons": [f"예탁금 {pct(dgp)} · 거래대금 {pct(vgp)} · 신용융자 {pct(cgp)} 백분위 모두 ≥ 60"]}
    return {"key": "neutral", "label": REGIMES["neutral"],
            "reasons": [f"신용융자 {pct(cgp)} · 예탁금 {pct(dgp)} · 거래대금 {pct(vgp)} 백분위 — 네 국면 조건에 해당하지 않음"]}


METRICS = [  # (키, 라벨, 단위)
    ("credit_growth", "신용융자 증가율(20일)", "rate"),
    ("leverage", "레버리지 강도(신용융자/시총)", "ratio"),
    ("turnover", "시장 회전 강도(20일 거래대금/시총)", "ratio"),
    ("deposit_growth", "예탁금 증가율(20일)", "rate"),
    ("value_growth", "거래대금 증가율(20일 평균)", "rate"),
    ("indiv_share", "개인 거래 비중(20일)", "ratio"),
    ("indiv_net_20", "개인 순매수(20일)", "krw"),
    ("lev_pref", "레버리지 ETF 선호도(20일)", "ratio"),
    ("inv_pref", "인버스 ETF 선호도(20일)", "ratio"),
    ("forced_20", "반대매매(20일 합)", "krw"),
    ("accounts_growth", "활동계좌 증가율(20일)", "rate"),
]


def _metrics(p: dict, prev: dict | None) -> list[dict]:
    return [{"key": k, "label": label, "unit": unit, "value": p.get(k), "pctile": p.get(f"{k}_pct"),
             "pctile_change": round(p.get(f"{k}_pct") - prev.get(f"{k}_pct"), 1) if prev and p.get(f"{k}_pct") is not None and prev.get(f"{k}_pct") is not None else None}
            for k, label, unit in METRICS]


def computed(conn) -> list[dict]:
    return with_percentiles(series(conn))


def summary(conn) -> dict:
    pts = [p for p in computed(conn) if p.get("credit_total") is not None]
    if not pts:
        return {"as_of": None, "regime": None, "metrics": [], "levels": {}, "krx_configured": krx_configured(), "accounts_available": False}
    p, prev = pts[-1], (pts[-1 - WINDOW] if len(pts) > WINDOW else None)
    return {"as_of": p["date"], "regime": classify(p), "metrics": _metrics(p, prev),
            "levels": {"credit_total": p["credit_total"], "deposits": p["deposits"], "kospi_close": p["kospi_close"]},
            "krx_configured": krx_configured(), "accounts_available": any(x.get("accounts_growth") is not None for x in pts[-60:])}


def history(conn, days: int = 1500) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    keep = ["date", "credit_total", "deposits", "kospi_close", "value", "credit_growth", "credit_growth_pct", "deposit_growth_pct",
            "value_growth_pct", "leverage", "turnover", "indiv_share", "forced_20_pct"]
    return [{k: p.get(k) for k in keep} for p in computed(conn) if p["date"] >= since and p.get("credit_total") is not None]


def save_snapshots(conn) -> int:
    pts = computed(conn)
    n = 0
    for key, name, start, end in EPISODES:
        window = [p for p in pts if start <= p["date"] <= end and p.get("credit_growth_pct") is not None]
        if not window:
            continue
        peak = max(window, key=lambda p: p["credit_growth_pct"])
        payload = {"name": name, "regime": classify(peak), "metrics": _metrics(peak, None),
                   "levels": {"credit_total": peak["credit_total"], "deposits": peak["deposits"], "kospi_close": peak["kospi_close"]}}
        conn.execute("INSERT OR REPLACE INTO retail_snapshots (episode, date, metrics_json, updated_at) VALUES (?, ?, ?, ?)",
                     (key, peak["date"], json.dumps(payload, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
        n += 1
    conn.commit()
    return n


def snapshots(conn) -> list[dict]:
    ensure_schema(conn)
    order = {k: i for i, (k, *_rest) in enumerate(EPISODES)}
    rows = [{"episode": r["episode"], "date": r["date"], **json.loads(r["metrics_json"])}
            for r in conn.execute("SELECT * FROM retail_snapshots")]
    return sorted(rows, key=lambda r: order.get(r["episode"], 99))

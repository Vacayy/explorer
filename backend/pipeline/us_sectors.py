"""미국 섹터 지도 · 섹터 화면 (ia-redesign §4.36) — 섹터 ETF로 지도·순위·카드, 섹터 안 종목은 내 커버리지(팔로우 종목). 모델 호출 없음.

국내는 전 종목 시세로 섹터를 직접 계산하지만 미국 시세는 팔로우 140여 종목뿐이라 그대로 하면 '내 팔로우 지도'가 된다.
그래서 섹터 = GICS 11(SPDR 섹터 ETF) + 세부 업종 13(업종 ETF), 비교 지수 SPY. 섹터 안 종목은 팔로우 종목을
Yahoo `sector`·`industry`로 묶는다(`SECTOR_ETF`·`INDUSTRY_ETF`).

- ETF 대응표: 코드 상수 `ETFS`(DB 표 없음 — 바뀌면 코드와 함께 바뀐다).
- ETF·SPY 종가: 국내 대표 ETF와 같은 표 `sector_benchmark_prices`(티커가 겹치지 않는다: 국내 6자리 · ^KS11 · 미국 영문).
  yfinance 일괄 다운로드 1~2콜(이력이 없는 티커는 3년, 있으면 꼬리). 끝나지 않은 미국 정규장 봉(뉴욕 16:10 전)은 버린다.
- 팔로우 종목 업종: `us_ticker_sectors(ticker, sector, industry, fetched_at)` — 활성 팔로우 중 없거나 30일 지난 것만 `.info`로.
- 팔로우 종목 시세 꼬리: `us_prices`(stock_code 호환). 원래 화면을 열 때·실적 시즌 체인에서만 받아서 AVGO처럼
  한 번도 안 열린 종목은 행이 없었다 → 같은 잡에서 일괄 다운로드로 채운다(없으면 2년, 있으면 1개월).
- RS: 국내 `sector_rs`와 같은 창(D-328) — 장기 91일(≈3개월)·단기 7일(≈1주) 달력일 수익률의 24개 간 백분위.
  1개월·3개월은 21·63거래일(국내 `sector_view.quote`와 같음). 4주 경로 = 1·2·3·4주 전 시점의 RS.
- 실행: `scripts/collect_sector_benchmarks.py`(launchd `sectorbench`)의 `sector_benchmarks.run()` 안. GET은 저장분만 읽는다.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SPY = "SPY"
BACKFILL_DAYS = 3 * 366 + 10
TAIL_DAYS = 10
FOLLOW_BACKFILL = "2y"
FOLLOW_TAIL = "1mo"
INFO_MAX_AGE_DAYS = 30
INFO_SLEEP = 0.3
CARD_DAYS = 60
TRAIL_WEEKS = (1, 2, 3, 4)
R1M, R3M = 21, 63
MEMBER_SPARK = 63
DOC_DAYS = 10
DOC_TYPES = ("blog", "scrap", "web", "youtube", "transcript", "earnings_release")
DOC_LIMIT = 30

# (티커, 한국어 이름, ETF 정식 이름, 상위 GICS ETF 또는 None) — GICS 11은 SPDR 섹터 ETF
ETFS: list[tuple[str, str, str, str | None]] = [
    ("XLK", "기술", "Technology Select Sector SPDR", None),
    ("XLC", "커뮤니케이션", "Communication Services Select Sector SPDR", None),
    ("XLY", "경기소비재", "Consumer Discretionary Select Sector SPDR", None),
    ("XLF", "금융", "Financial Select Sector SPDR", None),
    ("XLV", "헬스케어", "Health Care Select Sector SPDR", None),
    ("XLI", "산업재", "Industrial Select Sector SPDR", None),
    ("XLP", "필수소비재", "Consumer Staples Select Sector SPDR", None),
    ("XLE", "에너지", "Energy Select Sector SPDR", None),
    ("XLU", "유틸리티", "Utilities Select Sector SPDR", None),
    ("XLB", "소재", "Materials Select Sector SPDR", None),
    ("XLRE", "부동산", "Real Estate Select Sector SPDR", None),
    ("SMH", "반도체", "VanEck Semiconductor ETF", "XLK"),
    ("IGV", "소프트웨어", "iShares Expanded Tech-Software Sector ETF", "XLK"),
    ("CIBR", "사이버보안", "First Trust NASDAQ Cybersecurity ETF", "XLK"),
    ("XBI", "바이오", "SPDR S&P Biotech ETF", "XLV"),
    ("IHI", "의료기기", "iShares U.S. Medical Devices ETF", "XLV"),
    ("KRE", "지역은행", "SPDR S&P Regional Banking ETF", "XLF"),
    ("IAI", "증권·자산운용", "iShares U.S. Broker-Dealers & Securities Exchanges ETF", "XLF"),
    ("ITA", "항공·방산", "iShares U.S. Aerospace & Defense ETF", "XLI"),
    ("PAVE", "인프라 건설", "Global X U.S. Infrastructure Development ETF", "XLI"),
    ("XHB", "주택건설", "SPDR S&P Homebuilders ETF", "XLY"),
    ("XRT", "소매", "SPDR S&P Retail ETF", "XLY"),
    ("XOP", "석유·가스 개발", "SPDR S&P Oil & Gas Exploration & Production ETF", "XLE"),
    ("URA", "우라늄·원자력", "Global X Uranium ETF", "XLE"),
]
META = {t: {"name": n, "full": f, "parent": p} for t, n, f, p in ETFS}
TICKERS = [t for t, *_ in ETFS]
# 카드 벽 순서 — GICS 순, 세부 업종은 상위 섹터 바로 뒤
GICS_ORDER = ["XLK", "XLF", "XLY", "XLC", "XLV", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB"]

# Yahoo sector → GICS ETF, Yahoo industry → 세부 업종 ETF
SECTOR_ETF = {"Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY", "Financial Services": "XLF",
              "Healthcare": "XLV", "Industrials": "XLI", "Consumer Defensive": "XLP", "Energy": "XLE", "Utilities": "XLU",
              "Basic Materials": "XLB", "Real Estate": "XLRE"}
INDUSTRY_ETF = {"Semiconductors": "SMH", "Semiconductor Equipment & Materials": "SMH",
                "Software - Infrastructure": "IGV", "Software - Application": "IGV",
                "Biotechnology": "XBI", "Medical Devices": "IHI", "Medical Instruments & Supplies": "IHI",
                "Banks - Regional": "KRE", "Capital Markets": "IAI", "Financial Data & Stock Exchanges": "IAI",
                "Aerospace & Defense": "ITA", "Engineering & Construction": "PAVE", "Infrastructure Operations": "PAVE",
                "Residential Construction": "XHB", "Specialty Retail": "XRT", "Internet Retail": "XRT",
                "Oil & Gas E&P": "XOP", "Uranium": "URA"}
# 세부 업종 대응에 쓰는 Yahoo 업종만 한국어로(나머지는 원문 그대로 보인다)
INDUSTRY_KO = {"Semiconductors": "반도체", "Semiconductor Equipment & Materials": "반도체 장비·소재",
               "Software - Infrastructure": "인프라 소프트웨어", "Software - Application": "응용 소프트웨어",
               "Biotechnology": "바이오", "Medical Devices": "의료기기", "Medical Instruments & Supplies": "의료 기구·소모품",
               "Banks - Regional": "지역은행", "Capital Markets": "증권·자산운용", "Financial Data & Stock Exchanges": "금융 데이터·거래소",
               "Aerospace & Defense": "항공·방산", "Engineering & Construction": "엔지니어링·건설", "Infrastructure Operations": "인프라 운영",
               "Residential Construction": "주택건설", "Specialty Retail": "전문 소매", "Internet Retail": "온라인 소매",
               "Oil & Gas E&P": "석유·가스 개발", "Uranium": "우라늄"}

# 이 산업의 데이터 — 미국 실적 시즌 섹터(earnings_chain.SECTORS 키) · 밸류체인 칸(value_chain.NODES 키) ·
# 대만 공급망 계층(국내 반도체 섹터와 같은 계층) · 같은 업종의 한국 섹터(sector_map 대분류)
US_SEASON = {"XLK": ["semis", "software", "server", "network"], "SMH": ["semis", "semicap"], "IGV": ["software"],
             "CIBR": ["software"], "XLC": ["hyperscale"], "XLU": ["power"], "URA": ["power"], "XLI": ["dcinfra"],
             "PAVE": ["dcinfra"], "ITA": ["space"], "XLY": ["auto"]}
VALUE_CHAIN = {"XLK": "ai_accel", "SMH": "ai_accel", "XLU": "power_grid", "XLI": "dc_infra", "PAVE": "dc_infra"}
TW_SECTOR = {"XLK": "반도체·전자부품", "SMH": "반도체·전자부품"}
KR_SECTOR = {"XLK": "반도체·전자부품", "SMH": "반도체·전자부품", "IGV": "IT서비스·SW", "CIBR": "IT서비스·SW",
             "XLC": "통신", "XLY": "유통·소비재", "XRT": "유통·소비재", "XHB": "건설·부동산", "XLF": "금융", "KRE": "금융",
             "IAI": "금융", "XLV": "바이오·헬스케어", "XBI": "바이오·헬스케어", "IHI": "바이오·헬스케어", "XLI": "기계·장비",
             "ITA": "항공·방산·우주", "PAVE": "건설·부동산", "XLP": "음식료·농수산", "XLE": "화학·소재", "XOP": "화학·소재",
             "URA": "전력·에너지", "XLU": "전력·에너지", "XLB": "화학·소재", "XLRE": "건설·부동산"}


# ---------- 순수 규칙 (테스트 대상) ----------

def etf_of(sector: str | None, industry: str | None) -> tuple[str | None, str | None]:
    """Yahoo sector·industry → (GICS ETF, 세부 업종 ETF). 세부 업종 ETF의 상위가 GICS와 다르면(Yahoo 분류 차이) 세부는 버린다."""
    gics = SECTOR_ETF.get(sector or "")
    sub = INDUSTRY_ETF.get(industry or "")
    if sub and gics and META[sub]["parent"] != gics:
        sub = None
    return gics, sub


def closed_through(now: datetime | None = None) -> str:
    """종가로 저장해도 되는 마지막 미국 거래일(뉴욕 날짜) — 정규장 마감(16:00) 10분 뒤 전이면 어제까지(한국 시각 아침 6시 무렵)."""
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    day = now.date() if (now.hour, now.minute) >= (16, 10) else now.date() - timedelta(days=1)
    return day.isoformat()


def percentile(values: dict[str, float]) -> dict[str, float]:
    from pipeline.sector_rs import _percentile
    return _percentile(values)


def on_or_before(series: list[tuple[str, float]], day: str) -> float | None:
    """그날 이전 마지막 종가 (series는 날짜 오름차순)."""
    out = None
    for d, v in series:
        if d > day:
            break
        out = v
    return out


def cal_return(series: list[tuple[str, float]], as_of: str, days: int) -> float | None:
    """as_of 종가 / (as_of − days일 이전 마지막 종가) − 1, % — 국내 sector_rs와 같은 달력일 창."""
    cur = on_or_before(series, as_of)
    base = on_or_before(series, (date.fromisoformat(as_of) - timedelta(days=days)).isoformat())
    if not cur or not base:
        return None
    return (cur / base - 1) * 100


def rs_at(series: dict[str, list[tuple[str, float]]], as_of: str) -> dict[str, dict]:
    """as_of 시점 RS — 장기(91일)·단기(7일) 수익률의 ETF 간 백분위."""
    from pipeline.sector_rs import LONG_CAL_DAYS, SHORT_CAL_DAYS
    lg = {t: r for t, s in series.items() if (r := cal_return(s, as_of, LONG_CAL_DAYS)) is not None}
    sh = {t: r for t, s in series.items() if (r := cal_return(s, as_of, SHORT_CAL_DAYS)) is not None}
    pl, ps = percentile(lg), percentile(sh)
    return {t: {"rs_long": pl.get(t), "rs_short": ps.get(t)} for t in series}


def trading_return(values: list[float], n: int) -> float | None:
    if len(values) <= n or not values[-1 - n]:
        return None
    return round((values[-1] / values[-1 - n] - 1) * 100, 2)


def zone(rs_long: float | None, rs_short: float | None) -> str | None:
    if rs_long is None or rs_short is None:
        return None
    return ("주도" if rs_short >= 50 else "숨 고르기") if rs_long >= 50 else ("반등 시도" if rs_short >= 50 else "소외")


def members_of(etf: str, follows: list[dict]) -> list[dict]:
    """ETF의 내 커버리지 — GICS ETF면 그 섹터 전부(세부 업종 포함), 세부 업종 ETF면 그 업종만. 시총 큰 순."""
    key = "sub" if META[etf]["parent"] else "gics"
    out = [f for f in follows if f.get(key) == etf]
    return sorted(out, key=lambda f: -(f.get("market_cap") or 0))


def coverage_counts(follows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in follows:
        for k in (f.get("gics"), f.get("sub")):
            if k:
                out[k] = out.get(k, 0) + 1
    return out


def wall_order() -> list[str]:
    out = []
    for g in GICS_ORDER:
        out += [g] + [t for t, *_ in ETFS if META[t]["parent"] == g]
    return out


# ---------- 수집 (yfinance) ----------

def _yf_download(symbols: list[str], start: str, auto_adjust: bool):
    import yfinance as yf
    return yf.download(symbols, start=start, interval="1d", auto_adjust=auto_adjust, progress=False,
                       group_by="column", multi_level_index=True, threads=True)


def _frame_rows(df, symbols: list[str], field: str) -> dict[str, list[tuple[str, dict]]]:
    """yf.download 결과 → 티커 → [(날짜, {Open, High, Low, Close, Volume})]. 종가가 빈 봉은 버린다."""
    out: dict[str, list[tuple[str, dict]]] = {s: [] for s in symbols}
    if df is None or df.empty:
        return out
    dates = [idx.strftime("%Y-%m-%d") for idx in df.index]
    for s in symbols:
        if (field, s) not in df.columns:
            continue
        cols = {f: df[(f, s)].tolist() for f in ("Open", "High", "Low", "Close", "Volume") if (f, s) in df.columns}
        for i, d in enumerate(dates):
            c = cols[field][i]
            if c is None or c != c:
                continue
            out[s].append((d, {f: (None if v[i] is None or v[i] != v[i] else float(v[i])) for f, v in cols.items()}))
    return out


def collect_etfs(conn, download=_yf_download, now: datetime | None = None) -> dict:
    """ETF 24 + SPY 종가(수정 종가) → sector_benchmark_prices. 이력이 없는 티커는 3년, 있으면 꼬리만(일괄 1~2콜)."""
    through = closed_through(now)
    symbols = TICKERS + [SPY]
    ph = ",".join("?" * len(symbols))
    conn.execute(f"DELETE FROM sector_benchmark_prices WHERE ticker IN ({ph}) AND trade_date > ?", [*symbols, through])
    have = {r[0]: r[1] for r in conn.execute(
        f"SELECT ticker, COUNT(*) FROM sector_benchmark_prices WHERE ticker IN ({ph}) GROUP BY ticker", symbols)}
    groups = {BACKFILL_DAYS: [s for s in symbols if have.get(s, 0) < 200], TAIL_DAYS: [s for s in symbols if have.get(s, 0) >= 200]}
    n, ok, degraded = 0, [], []
    today = (now or datetime.now(timezone.utc)).astimezone(ET).date()
    for days, syms in groups.items():
        if not syms:
            continue
        try:
            rows = _frame_rows(download(syms, (today - timedelta(days=days)).isoformat(), True), syms, "Close")
        except Exception as e:  # noqa: BLE001 — 묶음 하나가 실패해도 나머지는 받는다(이름으로 보고)
            degraded += [f"{s}({type(e).__name__})" for s in syms]
            continue
        for s in syms:
            got = [(s, d, round(r["Close"], 4)) for d, r in rows[s] if d <= through]
            if not got:
                degraded.append(s)
                continue
            conn.executemany("INSERT OR REPLACE INTO sector_benchmark_prices (ticker, trade_date, close) VALUES (?, ?, ?)", got)
            n += len(got)
            ok.append(s)
    conn.commit()
    return {"rows": n, "tickers": ok, "degraded": degraded}


def _yf_info(ticker: str) -> dict:
    import yfinance as yf
    return yf.Ticker(ticker).info or {}


def collect_sectors(conn, info=_yf_info, sleep: float = INFO_SLEEP) -> dict:
    """활성 팔로우 중 업종이 없거나 30일 지난 티커만 Yahoo `.info`의 sector·industry를 받는다."""
    due = [r[0] for r in conn.execute(f"""SELECT t.ticker FROM transcript_follow t
        LEFT JOIN us_ticker_sectors s ON s.ticker = t.ticker
        WHERE t.active = 1 AND (s.ticker IS NULL OR s.fetched_at < datetime('now', '-{INFO_MAX_AGE_DAYS} days'))
        ORDER BY t.ticker""")]
    ok, failed = 0, []
    for i, t in enumerate(due):
        if i and sleep:
            time.sleep(sleep)
        try:
            d = info(t)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{t}({type(e).__name__})")
            continue
        conn.execute("""INSERT INTO us_ticker_sectors (ticker, sector, industry, fetched_at) VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(ticker) DO UPDATE SET sector=excluded.sector, industry=excluded.industry, fetched_at=excluded.fetched_at""",
                     (t, d.get("sector"), d.get("industry")))
        ok += 1
    conn.commit()
    return {"due": len(due), "fetched": ok, "failed": failed}


def collect_follow_prices(conn, download=_yf_download, now: datetime | None = None) -> dict:
    """활성 팔로우 종목 일봉 꼬리 → us_prices(원 종가, us_data.fetch_prices와 같은 auto_adjust=False). 없으면 2년."""
    through = closed_through(now)
    follows = [r[0] for r in conn.execute("SELECT ticker FROM transcript_follow WHERE active = 1 ORDER BY ticker")]
    if not follows:
        return {"rows": 0, "tickers": 0, "missing": []}
    have = {r[0]: r[1] for r in conn.execute(
        f"SELECT stock_code, COUNT(*) FROM us_prices WHERE stock_code IN ({','.join('?' * len(follows))}) AND close IS NOT NULL GROUP BY stock_code",
        follows)}
    today = (now or datetime.now(timezone.utc)).astimezone(ET).date()
    groups = {730: [t for t in follows if have.get(t, 0) < 200], 31: [t for t in follows if have.get(t, 0) >= 200]}
    n, got_t, missing = 0, 0, []
    for days, syms in groups.items():
        if not syms:
            continue
        try:
            rows = _frame_rows(download(syms, (today - timedelta(days=days)).isoformat(), False), syms, "Close")
        except Exception as e:  # noqa: BLE001
            missing += [f"{s}({type(e).__name__})" for s in syms]
            continue
        for s in syms:
            vals = [(s, d, r.get("Open"), r.get("High"), r.get("Low"), r["Close"], r.get("Volume")) for d, r in rows[s] if d <= through]
            if not vals:
                missing.append(s)
                continue
            conn.executemany("""INSERT INTO us_prices (stock_code, trade_date, open, high, low, close, volume, fetched_at)
                VALUES (?,?,?,?,?,?,?, datetime('now'))
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low,
                  close=excluded.close, volume=excluded.volume, fetched_at=excluded.fetched_at""", vals)
            n += len(vals)
            got_t += 1
    conn.commit()
    return {"rows": n, "tickers": got_t, "missing": missing}


def collect(conn) -> dict:
    """일별 실행 — ETF·SPY 종가 + 팔로우 업종(30일 주기) + 팔로우 시세 꼬리. 실패는 degraded에 이름으로."""
    etf = collect_etfs(conn)
    sec = collect_sectors(conn)
    px = collect_follow_prices(conn)
    return {"etf": etf, "sectors": sec, "follow_prices": px,
            "degraded": etf["degraded"] + [f"info:{x}" for x in sec["failed"]] + [f"px:{x}" for x in px["missing"]]}


# ---------- 읽기 ----------

def _series(conn) -> dict[str, list[tuple[str, float]]]:
    symbols = TICKERS + [SPY]
    out: dict[str, list[tuple[str, float]]] = {s: [] for s in symbols}
    for t, d, c in conn.execute(
            f"SELECT ticker, trade_date, close FROM sector_benchmark_prices WHERE ticker IN ({','.join('?' * len(symbols))}) "
            "ORDER BY trade_date", symbols):
        out[t].append((d, c))
    return out


def follows(conn) -> list[dict]:
    """활성 팔로우 + Yahoo 업종 + ETF 대응."""
    rows = []
    for r in conn.execute("""SELECT t.ticker, t.company_name, t.entity_id, t.market_cap, s.sector, s.industry
            FROM transcript_follow t LEFT JOIN us_ticker_sectors s ON s.ticker = t.ticker WHERE t.active = 1"""):
        gics, sub = etf_of(r["sector"], r["industry"])
        rows.append({"ticker": r["ticker"], "name": r["company_name"], "entity_id": r["entity_id"], "market_cap": r["market_cap"],
                     "sector": r["sector"], "industry": r["industry"], "gics": gics, "sub": sub})
    return rows


def _rs_bundle(series: dict[str, list[tuple[str, float]]], as_of: str) -> tuple[dict, dict]:
    etfs = {t: series[t] for t in TICKERS if series[t]}
    now = rs_at(etfs, as_of)
    d = date.fromisoformat(as_of)
    trails = {w: rs_at(etfs, (d - timedelta(weeks=w)).isoformat()) for w in TRAIL_WEEKS}
    return now, trails


def _etf_row(t: str, series: dict, now: dict, trails: dict, as_of: str, cov: dict[str, int]) -> dict:
    from pipeline.sector_rs import SHORT_CAL_DAYS
    s = series[t]
    vals = [v for _, v in s]
    chg_1w = cal_return(s, as_of, SHORT_CAL_DAYS) if s else None
    return {"ticker": t, "name": META[t]["name"], "full_name": META[t]["full"], "parent": META[t]["parent"],
            "last": vals[-1] if vals else None, "last_date": s[-1][0] if s else None,
            "chg_1d": trading_return(vals, 1), "ret_1m": trading_return(vals, R1M), "ret_3m": trading_return(vals, R3M),
            "chg_1w": round(chg_1w, 2) if chg_1w is not None else None,
            "rs_long": now.get(t, {}).get("rs_long"), "rs_short": now.get(t, {}).get("rs_short"),
            "trail": [{"weeks_ago": w, "rs_long": trails[w].get(t, {}).get("rs_long"),
                       "rs_short": trails[w].get(t, {}).get("rs_short")} for w in TRAIL_WEEKS],
            "coverage": cov.get(t, 0)}


def us_map(conn) -> dict:
    series = _series(conn)
    if not series[SPY]:
        return {'as_of': None, 'spy': [], 'sectors': []}
    return us_map_from_data(series, follows(conn))


def us_map_from_data(series: dict, followed: list[dict]) -> dict:
    """Build the existing map from already-loaded price and coverage data."""
    as_of = series[SPY][-1][0] if series[SPY] else None
    if not as_of:
        return {"as_of": None, "spy": [], "sectors": []}
    now, trails = _rs_bundle(series, as_of)
    cov = coverage_counts(followed)
    rows = []
    for t in wall_order():
        if not series[t]:
            continue
        rows.append({**_etf_row(t, series, now, trails, as_of, cov), "series": [v for _, v in series[t][-CARD_DAYS - 1:]]})
    return {"as_of": as_of, "spy": [v for _, v in series[SPY][-CARD_DAYS - 1:]], "sectors": rows}


def _member_rows(conn, members: list[dict], as_of: str) -> list[dict]:
    from pipeline.sector_rs import SHORT_CAL_DAYS
    out = []
    since = (date.fromisoformat(as_of) - timedelta(days=200)).isoformat()
    for m in members:
        s = [(r[0], r[1]) for r in conn.execute(
            "SELECT trade_date, close FROM us_prices WHERE stock_code = ? AND close IS NOT NULL AND trade_date >= ? ORDER BY trade_date",
            (m["ticker"], since))]
        vals = [v for _, v in s]
        w = cal_return(s, s[-1][0], SHORT_CAL_DAYS) if s else None
        out.append({"ticker": m["ticker"], "name": m["name"], "market_cap": m["market_cap"],
                    "industry": INDUSTRY_KO.get(m["industry"] or "", m["industry"]),
                    "ret_1w": round(w, 2) if w is not None else None, "ret_1m": trading_return(vals, R1M), "ret_3m": trading_return(vals, R3M),
                    "closes": vals[-MEMBER_SPARK - 1:]})
    return out


def _docs(conn, members: list[dict], as_of: str) -> list[dict]:
    ids = [m["entity_id"] for m in members if m["entity_id"]]
    if not ids:
        return []
    since = (date.fromisoformat(as_of) - timedelta(days=DOC_DAYS)).isoformat()
    ph, tp = ",".join("?" * len(ids)), ",".join("?" * len(DOC_TYPES))
    return [{"id": r["id"], "type": r["source_type"], "title": (r["title"] or "").strip() or "(제목 없음)",
             "published_at": r["published_at"], "hits": r["hits"]} for r in conn.execute(f"""
        SELECT d.id, d.source_type, d.title, d.published_at, COUNT(DISTINCT el.entity_id) hits
        FROM entity_links el JOIN raw_documents d ON d.id = el.doc_id
        WHERE el.entity_id IN ({ph}) AND d.published_at >= ? AND d.source_type IN ({tp})
        GROUP BY d.id ORDER BY hits DESC, d.published_at DESC LIMIT {DOC_LIMIT}""", [*ids, since, *DOC_TYPES])]


def _link(kind: str, label: str, title: str, sub: str, href: str, value=None, value_kind=None, count=0, verdict=None) -> dict:
    return {"kind": kind, "label": label, "title": title, "value": value, "value_kind": value_kind, "change": None,
            "sub": sub, "count": count, "href": href, "filtered": True, "verdict": verdict}


def data_links(conn, etf: str, n_members: int) -> list[dict]:
    import json
    import statistics
    out = []
    keys = US_SEASON.get(etf)
    if keys:
        from pipeline.earnings_chain import SECTORS
        ph = ",".join("?" * len(keys))
        season = conn.execute(f"SELECT max(season) FROM season_themes WHERE sector IN ({ph})", keys).fetchone()[0]
        rows = {r["sector"]: r for r in conn.execute(
            f"SELECT sector, verdict, body_json FROM season_themes WHERE season = ? AND sector IN ({ph}) ORDER BY id", [season, *keys])} if season else {}
        key = next((k for k in keys if k in rows), keys[0])
        row = rows.get(key)
        one = ((json.loads(row["body_json"] or "{}") or {}).get("one_line") if row else None) or ("판정 대기" if row else "이번 시즌 판정 없음")
        out.append(_link("usSeason", "미국 실적 시즌", f"{SECTORS.get(key, (key,))[0]} 섹터" + (f" · {season}" if season else ""), one,
                         f"/follow/transcripts?view=season&sector={key}", count=n_members, verdict=row["verdict"] if row else None))
    node = VALUE_CHAIN.get(etf)
    if node:
        from pipeline.value_chain import NODES
        hit = next((x for x in NODES if x[0] == node), None)
        if hit:
            out.append(_link("valuechain", "밸류체인", hit[1], hit[4], f"/value-chain?node={node}"))
    tw_sector = TW_SECTOR.get(etf)
    if tw_sector:
        from pipeline.sector_view import TW_LAYERS
        from pipeline.tw_universe import COMPANIES, LAYERS
        layers = TW_LAYERS[tw_sector]
        codes = [c for c, _n, layer, *_ in COMPANIES if layer in layers]
        ym = conn.execute("SELECT max(ym) FROM tw_monthly_revenue").fetchone()[0]
        yoys = [r[0] for r in conn.execute(
            f"SELECT yoy_pct FROM tw_monthly_revenue WHERE ym = ? AND yoy_pct IS NOT NULL AND code IN ({','.join('?' * len(codes))})",
            [ym, *codes])] if ym and codes else []
        names = dict(LAYERS)
        out.append(_link("taiwan", "대만 공급망", f"{names[layers[0]]} 외 {len(layers) - 1}계층 {len(codes)}사",
                         f"{int(ym[5:7])}월 월매출 전년 대비 중앙값" if ym and yoys else "월매출 대기", "/follow/taiwan",
                         value=round(statistics.median(yoys), 1) if yoys else None, value_kind="pct" if yoys else None, count=len(codes)))
        out[-1]["filtered"] = False
    kr = KR_SECTOR.get(etf)
    if kr:
        from pipeline.sector_rs import compute_sector_map
        g = next((x for x in compute_sector_map()["groups"] if x["name"] == kr), None)
        if g:
            rs = f"RS {'-' if g['rs_long'] is None else round(g['rs_long'])}·{'-' if g['rs_short'] is None else round(g['rs_short'])}"
            out.append(_link("krSector", "한국 섹터", kr, "같은 업종의 한국 상대강도", f"/industry/{kr}", verdict=rs))
    return out


def us_sector_detail(conn, etf: str) -> dict | None:
    etf = etf.upper()
    if etf not in META:
        return None
    series = _series(conn)
    as_of = series[SPY][-1][0] if series[SPY] else None
    fol = follows(conn)
    cov = coverage_counts(fol)
    if not as_of or not series[etf]:
        now, trails = {}, {w: {} for w in TRAIL_WEEKS}
        as_of_ = as_of or date.today().isoformat()
    else:
        now, trails = _rs_bundle(series, as_of)
        as_of_ = as_of
    head = _etf_row(etf, series, now, trails, as_of_, cov)
    parent = META[etf]["parent"] or etf
    sib_t = [parent] + [t for t, *_ in ETFS if META[t]["parent"] == parent]
    siblings = [{k: v for k, v in _etf_row(t, series, now, trails, as_of_, cov).items()
                 if k in ("ticker", "name", "parent", "ret_1m", "ret_3m", "rs_long", "rs_short")} for t in sib_t]
    members = members_of(etf, fol)
    spy = dict(series[SPY])
    return {
        "as_of": as_of, **head, "zone": zone(head["rs_long"], head["rs_short"]),
        "parent_name": META[META[etf]["parent"]]["name"] if META[etf]["parent"] else None,
        "series": [{"d": d, "v": v, "k": spy.get(d)} for d, v in series[etf]],
        "siblings": siblings,
        "members": _member_rows(conn, members, as_of_),
        "docs": _docs(conn, members, as_of_),
        "data_links": data_links(conn, etf, len(members)),
    }

"""섹터 대표지수 (ia-redesign §4.35, D-327-4) — 섹터마다 실제 ETF를 대표지수로, 없으면 Explorer 계산 지수. 모델 호출 없음.

- 대응표 `sector_benchmarks(sector, ticker, name, tracks, note)` — 원본은 코드의 `SEED`(init마다 맞춘다). ticker가 NULL이면
  대응 ETF가 없는 섹터다. 화면은 'Explorer 계산 지수(시총 가중)'라고 밝히고 이름을 지어내지 않는다.
  ETF는 2026-11-06 yfinance(`<코드>.KS` 이름·종가)와 네이버 종목 API(한글 이름·기초지수·상위 구성)로 확인했다.
- 일별 종가 `sector_benchmark_prices(ticker, trade_date, close)`(수정 종가) — ETF와 코스피(`^KS11`, 3년 비교용)를 yfinance로 받는다.
  표가 비었으면 3년 백필, 있으면 꼬리만. 1회 실행 = 대응 ETF 수 + 1콜(18 이하). KRX·pykrx는 쓰지 않는다.
- 계산 지수 `sector_index(sector, trade_date, value)` — 섹터 종목 시총 가중, 최신 주식 수 고정(`sector_rs`와 같은 방식).
  하루 수익률을 '전날 시총(최신 주식 수 × 전날 종가)' 가중으로 이어 붙인다(체인). 가격이 빈 종목은 그날만 빠진다.
  최신 시총 기준 섹터의 COVERAGE 이상이 가격을 가진 첫날부터 100으로 시작한다(이력이 얇은 과거를 버린다).
- 실행: `scripts/collect_sector_benchmarks.py`(launchd `sectorbench`, 평일 일별 시세 뒤). GET은 저장분만 읽는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
KOSPI = "^KS11"
BACKFILL_DAYS = 3 * 366 + 10
TAIL_DAYS = 10
COVERAGE = 0.6

# (섹터, ETF 코드, ETF 이름, 기초지수, 비고) — 비고는 ETF 구성이 섹터와 어떻게 다른지(툴팁에 붙인다)
SEED: list[tuple[str, str | None, str | None, str | None, str | None]] = [
    ("반도체·전자부품", "091160", "KODEX 반도체", "KRX 반도체", None),
    ("금융", "139270", "TIGER 200 금융", "코스피 200 금융", None),
    ("2차전지·에너지소재", "364980", "TIGER 2차전지TOP10", "KRX 2차전지 TOP 10", "POSCO홀딩스·LG화학도 함께 담습니다."),
    ("전력·에너지", "487240", "KODEX AI전력핵심설비", "iSelect AI 전력핵심설비",
     "전력 설비 중심이라 한국전력·SK이노베이션·두산에너빌리티는 담지 않습니다. 2024년 상장이라 그 전 시세는 없습니다."),
    ("조선·해운·운송", "441540", "HANARO Fn조선해운", "FnGuide 조선해운", "조선·해운 중심이라 육상·항공 운송은 담지 않습니다."),
    ("항공·방산·우주", "463250", "TIGER K방산&우주", "iSelect K방산&우주", None),
    ("유통·소비재", None, None, None, "구성이 맞는 ETF가 없습니다(삼성물산·화장품·유통이 섞인 섹터)."),
    ("건설·부동산", "117700", "KODEX 건설", "KRX 건설", None),
    ("기계·장비", None, None, None, "KODEX 기계장비(102960)는 두산에너빌리티·LG에너지솔루션·조선사 비중이 커 이 섹터(로봇·건설기계)와 다릅니다."),
    ("화학·소재", "117460", "KODEX 에너지화학", "KRX 에너지화학", "정유(SK이노베이션·S-Oil)도 함께 담습니다."),
    ("바이오·헬스케어", "266420", "KODEX 헬스케어", "KRX 헬스케어", None),
    ("자동차·모빌리티", "091180", "KODEX 자동차", "KRX 자동차", None),
    ("IT서비스·SW", "157490", "TIGER 소프트웨어", "FnGuide 소프트웨어", None),
    ("지주·기타", None, None, None, "TIGER 지주회사(307520)는 이 섹터 시총 1위 SK스퀘어를 담지 않아 쓰지 않습니다."),
    ("철강·금속", "117680", "KODEX 철강", "KRX 철강", None),
    ("음식료·농수산", "266410", "KODEX 필수소비재", "KRX 필수소비재", "화장품(에이피알·아모레퍼시픽 등)도 함께 담습니다."),
    ("통신", None, None, None, "통신 업종 ETF가 없습니다."),
    ("미디어·엔터·게임", "228810", "TIGER 미디어컨텐츠", "WISE 미디어컨텐츠", "미디어·엔터 중심이라 게임·카지노는 담지 않습니다."),
]


def seed(conn) -> int:
    """대응표를 SEED에 맞춘다 → 바뀐 행 수(멱등). SEED에 없는 섹터 행은 지운다."""
    before = conn.total_changes
    conn.executemany("""INSERT INTO sector_benchmarks (sector, ticker, name, tracks, note) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sector) DO UPDATE SET ticker=excluded.ticker, name=excluded.name, tracks=excluded.tracks, note=excluded.note
        WHERE (sector_benchmarks.ticker, sector_benchmarks.name, sector_benchmarks.tracks, sector_benchmarks.note)
              IS NOT (excluded.ticker, excluded.name, excluded.tracks, excluded.note)""", SEED)
    keep = {s[0] for s in SEED}
    gone = [(r[0],) for r in conn.execute("SELECT sector FROM sector_benchmarks") if r[0] not in keep]
    conn.executemany("DELETE FROM sector_benchmarks WHERE sector = ?", gone)
    conn.commit()
    return conn.total_changes - before


def benchmarks(conn) -> dict[str, dict]:
    """섹터 → {ticker, name, tracks, note, kind}. kind = 'etf' | 'computed'."""
    return {r["sector"]: {"ticker": r["ticker"], "name": r["name"], "tracks": r["tracks"], "note": r["note"],
                          "kind": "etf" if r["ticker"] else "computed"}
            for r in conn.execute("SELECT sector, ticker, name, tracks, note FROM sector_benchmarks")}


# ---------- 수집 (yfinance) ----------

def _yf_closes(symbol: str, days: int) -> list[tuple[str, float]]:
    import yfinance as yf
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    h = yf.Ticker(symbol).history(start=start)["Close"].dropna()
    return [(idx.strftime("%Y-%m-%d"), round(float(v), 2)) for idx, v in h.items()]


def _symbol(ticker: str) -> str:
    return ticker if ticker.startswith("^") else f"{ticker}.KS"


def _closed_through(now: datetime | None = None) -> str:
    """종가로 저장해도 되는 마지막 날(KST) — 정규장 마감(15:30) 10분 뒤 전이면 어제까지. 장중 값은 종가가 아니다."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    day = now.date() if (now.hour, now.minute) >= (15, 40) else now.date() - timedelta(days=1)
    return day.isoformat()


def collect(conn, fetch=_yf_closes, now: datetime | None = None) -> dict:
    """ETF·코스피 종가를 받아 저장 → {rows, tickers, degraded}. 표에 이력이 없으면 3년, 있으면 꼬리만.
    장중에 돌면 오늘 봉(장중 값)은 버린다."""
    tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM sector_benchmarks WHERE ticker IS NOT NULL ORDER BY ticker")]
    tickers.append(KOSPI)
    through = _closed_through(now)
    conn.execute("DELETE FROM sector_benchmark_prices WHERE trade_date > ?", (through,))
    n, ok, degraded = 0, [], []
    for t in tickers:
        have = conn.execute("SELECT COUNT(*) FROM sector_benchmark_prices WHERE ticker = ?", (t,)).fetchone()[0]
        try:
            rows = [(d, v) for d, v in fetch(_symbol(t), TAIL_DAYS if have >= 200 else BACKFILL_DAYS) if d <= through]
        except Exception as e:  # noqa: BLE001 — 하나가 실패해도 나머지는 받는다(이름으로 보고)
            degraded.append(f"{t}({type(e).__name__})")
            continue
        if not rows:
            degraded.append(t)
            continue
        conn.executemany("INSERT OR REPLACE INTO sector_benchmark_prices (ticker, trade_date, close) VALUES (?, ?, ?)",
                         [(t, d, v) for d, v in rows])
        n += len(rows)
        ok.append(t)
    conn.commit()
    return {"rows": n, "tickers": ok, "degraded": degraded}


# ---------- 계산 지수 ----------

def chain_index(prices: dict[str, dict[str, float]], weights: dict[str, float], latest: dict[str, float],
                coverage: float = COVERAGE) -> list[tuple[str, float]]:
    """순수 계산(테스트 대상). prices = 종목 → {날짜: 종가}, weights = 종목 → 최신 시총, latest = 종목 → 최신 종가.

    하루 수익률 = Σ 전날 시총(최신 주식 수 × 전날 종가) × 수익률 / Σ 전날 시총 — 그날·전날 가격이 모두 있는 종목만.
    시작일 = 가격을 가진 종목의 최신 시총 합이 전체의 coverage 이상인 첫날(100)."""
    total = sum(weights.values())
    if not total:
        return []
    dates = sorted({d for p in prices.values() for d in p})
    shares = {c: weights[c] / latest[c] for c in weights if latest.get(c)}
    out: list[tuple[str, float]] = []
    prev_d = None
    value = 100.0
    for d in dates:
        if not out:
            have = sum(weights[c] for c in shares if d in prices.get(c, {}))
            if have / total >= coverage:
                out.append((d, value))
                prev_d = d
            continue
        num = den = 0.0
        for c, s in shares.items():
            p = prices.get(c, {})
            if d in p and prev_d in p and p[prev_d]:
                cap = s * p[prev_d]
                num += cap * (p[d] / p[prev_d] - 1)
                den += cap
        if den:
            value *= 1 + num / den
        out.append((d, round(value, 4)))
        prev_d = d
    return out


def compute_index(conn) -> dict:
    """섹터별 계산 지수를 다시 계산해 통째로 바꿔 쓴다 → {sectors, rows}. 최근 3년 시세만 읽는다."""
    from pipeline.sector_rs import _members, _snapshot
    latest_day = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    if not latest_day:
        return {"sectors": 0, "rows": 0}
    members = _members(conn)
    snap = _snapshot(conn, latest_day)
    start = (datetime.fromisoformat(latest_day) - timedelta(days=BACKFILL_DAYS)).strftime("%Y-%m-%d")
    by_sector: dict[str, dict[str, dict[str, float]]] = {}
    for code, d, close in conn.execute(
            "SELECT stock_code, trade_date, close FROM stock_prices WHERE trade_date >= ? AND close IS NOT NULL", (start,)):
        g = members.get(code)
        if g and code in snap and snap[code][1]:
            by_sector.setdefault(g, {}).setdefault(code, {})[d] = close
    rows = []
    for g, prices in by_sector.items():
        weights = {c: snap[c][1] for c in prices}
        latest = {c: snap[c][0] for c in prices}
        rows += [(g, d, v) for d, v in chain_index(prices, weights, latest)]
    conn.execute("DELETE FROM sector_index")
    conn.executemany("INSERT INTO sector_index (sector, trade_date, value) VALUES (?, ?, ?)", rows)
    conn.commit()
    return {"sectors": len(by_sector), "rows": len(rows)}


def run() -> dict:
    """일별 실행 — 대표 ETF·코스피 종가 수집 + 계산 지수. 수집이 일부 실패하면 status='partial'."""
    from database import get_connection
    conn = get_connection()
    try:
        got = collect(conn)
        idx = compute_index(conn)
    finally:
        conn.close()
    out = {**got, "index": idx}
    if got["degraded"]:
        out["status"] = "partial"
    return out

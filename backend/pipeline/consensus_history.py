"""컨센서스 이력 수집 — 네이버 모바일 재무 API의 추정(E) 컬럼 일일 스냅샷.

투자자는 과거 실적이 아니라 forward를 산다 — Fwd EPS·PER의 '시계열'이
쌓여야 추정치 상향(revision)과 리레이팅(멀티플 변화)을 가를 수 있다.
기존 services/consensus_service(WiseReport 스냅샷, fwd PER 툴팁용)와 별개로
이력 전용: consensus_estimates 테이블에 (종목, 수집일, 연도) 단위 append.

소비 지점 (이력 축적 후):
- 상승 분해 v2: 주가 변화 = Fwd EPS revision × Fwd 멀티플 변화
- quadrant_gap 펀더 축 교체 (감성 프록시 → 추정치 방향)
- '이익 추정치 상향 반전' 신호 (턴어라운드 판정 핵심)
- 북극성 '시장 기대' 계량
"""
from datetime import date

import requests

from database import get_connection

_UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
_API = "https://m.stock.naver.com/api/stock/{code}/finance/annual"

_ROW_MAP = {"EPS": "fwd_eps", "PER": "fwd_per", "영업이익": "fwd_op",
            "매출액": "fwd_revenue", "ROE": "fwd_roe"}


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_estimates(stock_code: str) -> list[dict]:
    """종목 하나의 컨센서스(E) 연도별 추정치. 컨센서스 컬럼 없으면 []."""
    r = requests.get(_API.format(code=stock_code), headers=_UA, timeout=15)
    r.raise_for_status()
    info = r.json().get("financeInfo") or {}
    years = [c["key"] for c in info.get("trTitleList", []) if c.get("isConsensus") == "Y"]
    if not years:
        return []
    out = {y: {"fiscal_year": y} for y in years}
    for row in info.get("rowList", []):
        field = _ROW_MAP.get(row.get("title"))
        if not field:
            continue
        for y in years:
            cell = (row.get("columns") or {}).get(y) or {}
            out[y][field] = _num(cell.get("value"))
    return [v for v in out.values() if any(v.get(f) is not None for f in _ROW_MAP.values())]


def fetch_target(stock_code: str) -> dict:
    """목표주가 평균·투자의견 평균 (integration API consensusInfo)."""
    try:
        r = requests.get(f"https://m.stock.naver.com/api/stock/{stock_code}/integration",
                         headers=_UA, timeout=15)
        info = r.json().get("consensusInfo") or {}
        return {"target_price": _num(info.get("priceTargetMean")),
                "opinion": _num(info.get("recommMean"))}
    except Exception:
        return {}


def collect_snapshots(stock_codes: list[str] | None = None) -> dict:
    """워치리스트(기본) 종목의 일일 스냅샷 — 멱등 (종목·일·연도 UNIQUE)."""
    conn = get_connection()
    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in conn.execute("SELECT stock_code FROM watchlist")]
    today = date.today().isoformat()
    stats = {"stocks": len(stock_codes), "rows": 0, "failed": 0}
    for code in stock_codes:
        try:
            rows = fetch_estimates(code)
        except Exception:
            stats["failed"] += 1
            continue
        tgt = fetch_target(code)
        for est in rows:
            conn.execute("""
                INSERT INTO consensus_estimates
                    (stock_code, fetched_date, fiscal_year, fwd_eps, fwd_per, fwd_op,
                     fwd_revenue, fwd_roe, target_price, opinion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_code, fetched_date, fiscal_year) DO UPDATE SET
                    fwd_eps=excluded.fwd_eps, fwd_per=excluded.fwd_per, fwd_op=excluded.fwd_op,
                    fwd_revenue=excluded.fwd_revenue, fwd_roe=excluded.fwd_roe,
                    target_price=excluded.target_price, opinion=excluded.opinion
            """, (code, today, est["fiscal_year"], est.get("fwd_eps"), est.get("fwd_per"),
                  est.get("fwd_op"), est.get("fwd_revenue"), est.get("fwd_roe"),
                  tgt.get("target_price"), tgt.get("opinion")))
            stats["rows"] += 1
    conn.commit()
    conn.close()
    return stats


def ran_today(conn) -> bool:
    r = conn.execute("SELECT last_run_at FROM pipeline_runs WHERE name='consensus'").fetchone()
    return bool(r) and r["last_run_at"][:10] == date.today().isoformat()


def mark_ran(conn):
    conn.execute("INSERT OR REPLACE INTO pipeline_runs (name, last_run_at) VALUES ('consensus', datetime('now'))")
    conn.commit()

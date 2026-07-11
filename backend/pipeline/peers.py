"""Peer 그룹 — 종목별 비교 대상 (국내 + 해외).

- Peer 리스트: haiku 큐레이션 1회 → stock_peers 캐시 (LLM은 목록만, 지표는 데이터)
- 지표: KR = 자체 KPI 파이프라인 재사용 / US 등 해외 = yfinance (24h 캐시)
- 해외 회사는 종목코드가 없는 온톨로지 확장 지점 — 야후 티커가 자연키
"""
import json
import time

from database import get_connection
from pipeline.digests import _call_json
from pipeline.enrich import llm_engine

METRICS_TTL_SEC = 24 * 3600


def get_peer_list(stock_code: str, name: str) -> list[dict]:
    """캐시된 peer 목록 — 없으면 haiku 큐레이션 후 저장."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, ticker, market FROM stock_peers WHERE stock_code=? ORDER BY id",
        (stock_code,)).fetchall()
    if rows:
        conn.close()
        return [dict(r) for r in rows]

    if llm_engine() != "claude-code":
        conn.close()
        return []

    prompt = (
        f"한국 상장사 '{name}'({stock_code})의 사업 경쟁·비교 대상(peer) 3~5개를 골라라.\n"
        "국내·해외 모두 포함 가능. 실제 사업 영역이 겹치는 상장사만.\n"
        'JSON만 출력: {"peers": [{"name": "통용 한국어 표기", '
        '"ticker": "야후파이낸스 티커 (한국은 6자리코드.KS 또는 .KQ, 미국은 심볼)", '
        '"market": "KR|US|JP|TW|..."}]}'
    )
    try:
        data = _call_json(prompt)
    except Exception:
        conn.close()
        return []

    peers = []
    for p in (data.get("peers") or [])[:6]:
        if not (isinstance(p, dict) and p.get("name") and p.get("ticker")):
            continue
        ticker = str(p["ticker"]).strip().upper()
        market = str(p.get("market") or "").strip().upper() or ("KR" if ticker.endswith((".KS", ".KQ")) else "US")
        # KR peer는 실존 종목코드 검증 (환각 방지)
        if market == "KR":
            code = ticker.split(".")[0]
            row = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?", (code,)).fetchone()
            if not row:
                continue
        peers.append({"name": str(p["name"]).strip()[:30], "ticker": ticker, "market": market})

    for p in peers:
        conn.execute(
            "INSERT OR IGNORE INTO stock_peers (stock_code, name, ticker, market) VALUES (?, ?, ?, ?)",
            (stock_code, p["name"], p["ticker"], p["market"]))
    conn.commit()
    conn.close()
    return peers


def _yf_metrics(ticker: str) -> dict | None:
    """해외 peer 지표 — yfinance (marketCap USD 등)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        if not info.get("marketCap"):
            return None
        return {
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency") or "USD",
            "per_fwd": round(info["forwardPE"], 1) if info.get("forwardPE") else None,
            "op_margin": round(info["operatingMargins"] * 100, 1) if info.get("operatingMargins") is not None else None,
        }
    except Exception:
        return None


def get_peer_metrics(ticker: str, market: str) -> dict | None:
    """지표 조회 (24h 캐시). KR은 자체 KPI, 해외는 yfinance."""
    conn = get_connection()
    row = conn.execute("SELECT metrics_json, fetched_at FROM peer_metrics WHERE ticker=?",
                       (ticker,)).fetchone()
    if row:
        age = time.time() - time.mktime(time.strptime(row["fetched_at"], "%Y-%m-%d %H:%M:%S"))
        if age < METRICS_TTL_SEC:
            conn.close()
            return json.loads(row["metrics_json"])
    conn.close()

    if market == "KR":
        code = ticker.split(".")[0]
        m = _kr_metrics(code)
    else:
        m = _yf_metrics(ticker)
    if m is None:
        return None

    conn = get_connection()
    conn.execute("""
        INSERT INTO peer_metrics (ticker, metrics_json, fetched_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(ticker) DO UPDATE SET metrics_json=excluded.metrics_json,
            fetched_at=datetime('now')
    """, (ticker, json.dumps(m, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return m


def _kr_metrics(stock_code: str) -> dict | None:
    """국내 peer 지표 — 저장된 시세·펀더멘털에서 (외부 호출 없음)."""
    conn = get_connection()
    px = conn.execute("""
        SELECT close, market_cap FROM stock_prices WHERE stock_code=?
        ORDER BY trade_date DESC LIMIT 1""", (stock_code,)).fetchone()
    # PER(fwd): 컨센서스(최신 회계연도 추정) 우선 — trailing을 fwd로 표기하지 않는다
    fu = conn.execute("""
        SELECT per_est FROM consensus WHERE stock_code=? ORDER BY fiscal_year DESC LIMIT 1""",
        (stock_code,)).fetchone()
    # 영업이익률: 최근 연간 IS (KPI와 동일 소스 재사용은 무겁고, 근사로 컨센서스/재무 활용)
    op_margin = None
    row = conn.execute("""
        SELECT corp_code FROM companies WHERE stock_code=?""", (stock_code,)).fetchone()
    if row:
        rev = conn.execute("""
            SELECT thstrm_amount FROM financial_statements
            WHERE corp_code=? AND sj_div='IS' AND account_nm LIKE '%매출액%' AND reprt_code='11011'
            ORDER BY bsns_year DESC LIMIT 1""", (row["corp_code"],)).fetchone()
        op = conn.execute("""
            SELECT thstrm_amount FROM financial_statements
            WHERE corp_code=? AND sj_div='IS' AND account_nm LIKE '%영업이익%' AND reprt_code='11011'
            ORDER BY bsns_year DESC LIMIT 1""", (row["corp_code"],)).fetchone()
        try:
            r, o = float(rev["thstrm_amount"]), float(op["thstrm_amount"])
            if r:
                op_margin = round(o / r * 100, 1)
        except Exception:
            pass
    conn.close()
    if not px:
        return None
    return {
        "market_cap": px["market_cap"],
        "currency": "KRW",
        "per_fwd": round(fu["per_est"], 1) if fu and fu["per_est"] else None,
        "op_margin": op_margin,
    }

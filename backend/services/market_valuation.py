"""전종목 밸류 지표 수집 — 네이버 종목 통합 API (PER·PBR·EPS·BPS·배당).

pykrx fundamental이 KRX 로그인 벽에 막혀 있어 네이버를 쓴다. 예전 원천이던 시세 표
`finance.naver.com/sise/sise_market_sum.naver`는 2026-09-11부터 새 SPA(stock.naver.com)로 302 이동해
표가 비었고, 수집은 'stocks 0'을 찍으며 ok로 끝나 09-07 이후 한 달 넘게 묵었다.
지금은 종목별 `m.stock.naver.com/api/stock/{code}/integration`(컨센서스 이력과 같은 API)을 부른다.

- 대상: 최신 거래일 시세가 있는 종목(시총 내림차순). trade_date = 그 거래일(실행일이 아니라).
- ROE는 이 API에 없어 EPS/BPS×100으로 계산한다(최근 4분기 EPS ÷ 최근 BPS — 기말 자본 기준 근사).
- 멱등: 그 거래일에 이미 대상의 90% 이상이 있으면 건너뛴다.
- 저장: fundamentals(stock_code, trade_date) upsert. 실패율이 높으면 status로 남긴다(조용한 0건 금지).
"""
import re
import time

import requests

from database import get_connection

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_API = "https://m.stock.naver.com/api/stock/{code}/integration"
_FIELDS = {"per": "per", "pbr": "pbr", "eps": "eps", "bps": "bps", "dividendYieldRatio": "div_yield", "dividend": "dps"}
EARLY_ABORT = 20   # 처음 이만큼이 전부 실패면 원천이 막힌 것 — 나머지를 두드리지 않는다


def _num(s) -> float | None:
    m = re.search(r"-?[\d,]*\.?\d+", str(s or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_integration(body: dict) -> dict:
    """totalInfos → {per, pbr, eps, bps, div_yield, dps, roe}. 값 없음(N/A·-)은 None."""
    out = {col: None for col in _FIELDS.values()}
    for info in body.get("totalInfos") or []:
        col = _FIELDS.get(info.get("code"))
        if col:
            out[col] = _num(info.get("value"))
    eps, bps = out["eps"], out["bps"]
    out["roe"] = round(eps / bps * 100, 2) if eps is not None and bps and bps > 0 else None
    return out


def fetch_market_valuation(conn=None, get=None, pause: float = 0.05) -> dict:
    """최신 거래일 시세 보유 종목의 밸류 지표 → fundamentals upsert. 반환: 통계(+실패 시 status)."""
    own = conn is None
    conn = conn or get_connection()
    get = get or (lambda url: requests.get(url, headers=_HEADERS, timeout=10))
    try:
        day = conn.execute("SELECT max(trade_date) FROM stock_prices WHERE market_cap IS NOT NULL").fetchone()[0]
        if not day:
            return {"status": "error", "reason": "시세 없음"}
        codes = [r[0] for r in conn.execute(
            "SELECT stock_code FROM stock_prices WHERE trade_date=? AND market_cap IS NOT NULL ORDER BY market_cap DESC",
            (day,))]
        have = conn.execute("SELECT count(*) FROM fundamentals WHERE trade_date=?", (day,)).fetchone()[0]
        if codes and have >= len(codes) * 0.9:
            return {"date": day, "skipped": "already", "stocks": have}
        ok = failed = 0
        for i, code in enumerate(codes):
            try:
                r = get(_API.format(code=code))
                r.raise_for_status()
                v = parse_integration(r.json())
            except Exception:  # noqa: BLE001 — 종목 하나의 실패는 세고 넘어간다
                failed += 1
                if i + 1 == EARLY_ABORT and ok == 0:
                    return {"status": "error", "date": day, "reason": f"처음 {EARLY_ABORT}종목 전부 실패", "failed": failed}
                continue
            if any(v[k] is not None for k in ("per", "pbr", "eps", "bps")):
                conn.execute("""
                    INSERT INTO fundamentals (stock_code, trade_date, per, pbr, eps, bps, div_yield, dps, roe)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                        per=excluded.per, pbr=excluded.pbr, eps=excluded.eps, bps=excluded.bps,
                        div_yield=excluded.div_yield, dps=excluded.dps, roe=excluded.roe
                """, (code, day, v["per"], v["pbr"], v["eps"], v["bps"], v["div_yield"], v["dps"], v["roe"]))
                ok += 1
            if (i + 1) % 200 == 0:
                conn.commit()
            if pause:
                time.sleep(pause)
        conn.commit()
        stats = {"date": day, "targets": len(codes), "stocks": ok, "failed": failed}
        if codes and ok == 0:
            stats["status"] = "error"
        elif failed > len(codes) * 0.05:
            stats["status"] = "partial"
        return stats
    finally:
        if own:
            conn.close()

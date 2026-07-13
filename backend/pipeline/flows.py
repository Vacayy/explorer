"""수급 이력 수집 — 네이버 모바일 trend API (백로그 #23, '누가 사고 있는가').

거래량 신호가 '관심의 폭발'을 잡는다면, 수급은 그 다음 해상도 —
새 참여자가 외인인가 기관인가 개인인가. pykrx 투자자별 매매는 KRX 로그인
벽에 막혀(fundamentals와 동일) 네이버 trend API로 우회.
소비: 종목 브리프 [수급] 재료 블록. 신호화(연속 순매수 등)는 이력 축적 후.
"""
from datetime import date

import requests

from database import get_connection

_UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
_API = "https://m.stock.naver.com/api/stock/{code}/trend?pageSize=30"


def _num(v) -> int | None:
    try:
        return int(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def fetch_flows(stock_code: str) -> list[dict]:
    r = requests.get(_API.format(code=stock_code), headers=_UA, timeout=15)
    r.raise_for_status()
    out = []
    for row in r.json():
        bd = row.get("bizdate") or ""
        if len(bd) != 8:
            continue
        out.append({
            "trade_date": f"{bd[:4]}-{bd[4:6]}-{bd[6:]}",
            "foreign_net": _num(row.get("foreignerPureBuyQuant")),
            "inst_net": _num(row.get("organPureBuyQuant")),
            "indiv_net": _num(row.get("individualPureBuyQuant")),
            "foreign_hold_ratio": float(str(row.get("foreignerHoldRatio", "")).rstrip("%") or 0) or None,
            "close": _num(row.get("closePrice")),
        })
    return out


def collect_flows(stock_codes: list[str] | None = None) -> dict:
    """워치리스트(기본) 종목의 최근 30일 수급 upsert — 멱등."""
    conn = get_connection()
    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in conn.execute("SELECT stock_code FROM watchlist")]
    stats = {"stocks": len(stock_codes), "rows": 0, "failed": 0}
    for code in stock_codes:
        try:
            rows = fetch_flows(code)
        except Exception:
            stats["failed"] += 1
            continue
        for f in rows:
            conn.execute("""
                INSERT INTO investor_flows
                    (stock_code, trade_date, foreign_net, inst_net, indiv_net, foreign_hold_ratio, close)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                    foreign_net=excluded.foreign_net, inst_net=excluded.inst_net,
                    indiv_net=excluded.indiv_net, foreign_hold_ratio=excluded.foreign_hold_ratio,
                    close=excluded.close
            """, (code, f["trade_date"], f["foreign_net"], f["inst_net"], f["indiv_net"],
                  f["foreign_hold_ratio"], f["close"]))
            stats["rows"] += 1
    conn.commit()
    conn.close()
    return stats


def flow_summary(conn, stock_code: str, days: int = 20) -> dict | None:
    """브리프 재료용 — 최근 N거래일 누적 순매수 (주식 수)."""
    r = conn.execute(f"""
        SELECT SUM(foreign_net) f, SUM(inst_net) i, SUM(indiv_net) p, COUNT(*) n,
               (SELECT foreign_hold_ratio FROM investor_flows
                WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1) hold
        FROM (SELECT * FROM investor_flows WHERE stock_code=?
              ORDER BY trade_date DESC LIMIT {int(days)})""",
        (stock_code, stock_code)).fetchone()
    if not r or not r["n"]:
        return None
    return {"days": r["n"], "foreign_net": r["f"], "inst_net": r["i"],
            "indiv_net": r["p"], "foreign_hold_ratio": r["hold"]}


def ran_today(conn) -> bool:
    r = conn.execute("SELECT last_run_at FROM pipeline_runs WHERE name='flows'").fetchone()
    return bool(r) and r["last_run_at"][:10] == date.today().isoformat()


def mark_ran(conn):
    conn.execute("INSERT OR REPLACE INTO pipeline_runs (name, last_run_at) VALUES ('flows', datetime('now'))")
    conn.commit()

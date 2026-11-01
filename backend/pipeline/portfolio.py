"""포트폴리오 거래 원장과 비율 전용 수익률 (D-212, docs/specs/portfolio-ledger.md).

원화 금액은 portfolio_transactions.amount에만 있다. 이 모듈의 공개 함수(summary·history·transactions)는
비율(%)·가격·날짜만 반환한다 — 금액·수량을 응답에 싣지 않는 것이 계약이다.
묶음 객체는 D-185의 stock_groups(kind='portfolio')를 쓰고, 멤버에는 종목·편입일만 둔다
(quantity·avg_price를 채우면 기존 묶음 API가 원화 손익을 계산해 버린다).
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from database import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES stock_groups(id) ON DELETE CASCADE,
    trade_date  TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK(kind IN ('buy', 'sell', 'deposit', 'withdraw')),
    stock_code  TEXT,
    amount      REAL NOT NULL CHECK(amount > 0),
    price       REAL CHECK(price IS NULL OR price > 0),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_portfolio_tx ON portfolio_transactions(group_id, trade_date, id);
CREATE TABLE IF NOT EXISTS portfolio_quotes (      -- 보유 종목 장중 최신 시세(종목당 1행, 30분 TTL)
    stock_code    TEXT PRIMARY KEY,
    price         REAL,
    change_pct    REAL,
    market_status TEXT,
    traded_at     TEXT,
    fetched_at    REAL
);
"""
GROUP_NAME = "내 포트폴리오"
EPS = 1e-9
QUOTE_TTL = 30 * 60                      # 장중 시세 갱신 주기(초)
KST = timezone(timedelta(hours=9))


class LedgerError(ValueError):
    """원장이 음수 수량·현금이 되는 입력."""


def connect() -> sqlite3.Connection:
    """단일 진입점 — 테스트는 이 함수만 바꿔 임시 DB를 쓴다."""
    return get_connection()


# ── 원장 재생 (순수) ─────────────────────────────────────────────────────────

@dataclass
class Position:
    qty: float = 0.0
    avg: float = 0.0
    entry_date: str = ""


@dataclass
class Ledger:
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)


def apply(ledger: Ledger, tx: dict) -> None:
    """거래 한 건 적용. 매수는 이동평균 평단, 매도는 평단 유지(국내 증권사 관행)."""
    kind, amount = tx["kind"], float(tx["amount"])
    if kind == "deposit":
        ledger.cash += amount
    elif kind == "withdraw":
        if amount > ledger.cash + EPS:
            raise LedgerError(f"{tx['trade_date']} 출금액이 현금보다 큽니다.")
        ledger.cash -= amount
    elif kind == "buy":
        if amount > ledger.cash + EPS:
            raise LedgerError(f"{tx['trade_date']} 매수 금액이 현금보다 큽니다.")
        pos = ledger.positions.setdefault(tx["stock_code"], Position(entry_date=tx["trade_date"]))
        qty = amount / tx["price"]
        if pos.qty <= EPS:
            pos.entry_date = tx["trade_date"]
        pos.avg = (pos.avg * pos.qty + amount) / (pos.qty + qty)
        pos.qty += qty
        ledger.cash -= amount
    elif kind == "sell":
        pos = ledger.positions.get(tx["stock_code"])
        qty = amount / tx["price"]
        if not pos or qty > pos.qty * (1 + 1e-6) + EPS:
            raise LedgerError(f"{tx['trade_date']} 매도 수량이 보유보다 많습니다.")
        pos.qty = max(0.0, pos.qty - qty)
        ledger.cash += amount
        if pos.qty <= EPS:
            del ledger.positions[tx["stock_code"]]


def replay(txs: list[dict]) -> Ledger:
    ledger = Ledger()
    for tx in sorted(txs, key=lambda t: (t["trade_date"], t["id"])):
        apply(ledger, tx)
    return ledger


def realized_trades(txs: list[dict]) -> tuple[list[dict], float]:
    """매도마다 실현 손익(매도는 평단 유지라 (매도가 − 그 시점 평단) × 매도 수량). 

    반환: (비율·가격만 담은 매도 목록, 내부 계산용 실현 손익 합계[원화 — 응답에 싣지 않는다]).
    """
    ledger, out, gain = Ledger(), [], 0.0
    for tx in sorted(txs, key=lambda t: (t["trade_date"], t["id"])):
        before = ledger.positions.get(tx["stock_code"]) if tx["kind"] == "sell" else None
        avg, entry = (before.avg, before.entry_date) if before else (0.0, "")
        apply(ledger, tx)
        if tx["kind"] != "sell":
            continue
        gain += tx["amount"] / tx["price"] * (tx["price"] - avg)
        out.append({"code": tx["stock_code"], "entry_date": entry, "sell_date": tx["trade_date"],
                    "avg_price": round(avg, 2), "sell_price": tx["price"],
                    "return_pct": round((tx["price"] / avg - 1) * 100, 2) if avg > EPS else None,
                    "holding_days": (date.fromisoformat(tx["trade_date"]) - date.fromisoformat(entry)).days if entry else None,
                    "full": tx["stock_code"] not in ledger.positions})
    return out, gain


def entry_weights(txs: list[dict], prices: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """지금 보유 중인 포지션마다 '처음 연 매수'가 그 시점 계좌(현금 + 보유 평가액)에서 차지한 비중(%).

    이후 추가 매수는 보지 않는다 — '처음부터 크게 들어가지 말라'는 원칙(신규 진입 비중 상한, D-227 후속)의 재료.
    전량 청산 후 다시 사면 새 진입이다. 평가는 그날 이전 마지막 종가(없으면 평단).
    """
    ledger, out = Ledger(), {}
    for tx in sorted(txs, key=lambda t: (t["trade_date"], t["id"])):
        if tx["kind"] == "buy":
            pos = ledger.positions.get(tx["stock_code"])
            if not pos or pos.qty <= EPS:
                value = ledger.cash + sum(p.qty * (_close_on(prices.get(c, []), tx["trade_date"]) or p.avg)
                                          for c, p in ledger.positions.items())
                out[tx["stock_code"]] = round(tx["amount"] / value * 100, 2) if value > EPS else None
        apply(ledger, tx)
    return {code: w for code, w in out.items() if code in ledger.positions}


def _close_on(series: list[tuple[str, float]], day: str) -> float | None:
    """day 이전(포함) 마지막 종가."""
    last = None
    for d, c in series:
        if d > day:
            break
        last = c
    return last


def valuation(txs: list[dict], prices: dict[str, list[tuple[str, float]]]) -> list[dict]:
    """평가일별 TWR. 반환은 비율만: date, cum_return_pct, day_return_pct.

    r_t = V_t / (V_{t-1} + F_t) − 1, F_t = 그날 순입금(입금−출금). 거래는 장 시작 전에 일어난 것으로 본다.
    """
    if not txs:
        return []
    txs = sorted(txs, key=lambda t: (t["trade_date"], t["id"]))
    first = txs[0]["trade_date"]
    days = sorted({first} | {d for ser in prices.values() for d, _ in ser if d >= first})
    ledger, i, prev_value, growth, out = Ledger(), 0, 0.0, 1.0, []
    for day in days:
        flow = 0.0
        while i < len(txs) and txs[i]["trade_date"] <= day:
            tx = txs[i]
            apply(ledger, tx)
            flow += tx["amount"] if tx["kind"] == "deposit" else -tx["amount"] if tx["kind"] == "withdraw" else 0.0
            i += 1
        value = ledger.cash
        for code, pos in ledger.positions.items():
            close = _close_on(prices.get(code, []), day)
            value += pos.qty * (close if close is not None else pos.avg)   # 종가 미수집은 평단으로(수익 0)
        base = prev_value + flow
        r = value / base - 1 if base > EPS else 0.0
        growth *= 1 + r
        out.append({"date": day, "cum_return_pct": round((growth - 1) * 100, 4), "day_return_pct": round(r * 100, 4)})
        prev_value = value
    return out


# ── DB ──────────────────────────────────────────────────────────────────────

def group_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM stock_groups WHERE kind='portfolio' ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO stock_groups (name, kind) VALUES (?, 'portfolio')", (GROUP_NAME,))
    conn.commit()
    return cur.lastrowid


def _txs(conn: sqlite3.Connection, gid: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, trade_date, kind, stock_code, amount, price FROM portfolio_transactions "
        "WHERE group_id=? ORDER BY trade_date, id", (gid,))]


def _prices(conn: sqlite3.Connection, codes: set[str], since: str) -> dict[str, list[tuple[str, float]]]:
    out = {}
    for code in codes:
        rows = conn.execute("SELECT trade_date, close FROM stock_prices WHERE stock_code=? AND trade_date>=date(?, '-14 day') "
                            "AND close IS NOT NULL ORDER BY trade_date", (code, since)).fetchall()
        out[code] = [(r["trade_date"], float(r["close"])) for r in rows]
    return out


def _names(conn: sqlite3.Connection, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    q = ",".join("?" * len(codes))
    return {r["stock_code"]: r["corp_name"] for r in conn.execute(
        f"SELECT stock_code, corp_name FROM companies WHERE stock_code IN ({q})", tuple(codes))}


def _sync_members(conn: sqlite3.Connection, gid: int, ledger: Ledger) -> None:
    """묶음 멤버 = 현재 보유 종목. 종목·편입일만(수량·평단은 NULL 유지 — 프라이버시 계약)."""
    held = ledger.positions
    for code, pos in held.items():
        conn.execute("INSERT INTO stock_group_members (group_id, stock_code, bought_at) VALUES (?,?,?) "
                     "ON CONFLICT(group_id, stock_code) DO UPDATE SET bought_at=excluded.bought_at, quantity=NULL, avg_price=NULL",
                     (gid, code, pos.entry_date))
    q = ",".join("?" * len(held))
    conn.execute(f"DELETE FROM stock_group_members WHERE group_id=?" + (f" AND stock_code NOT IN ({q})" if held else ""),
                 (gid, *held))


def market_hours(now: datetime | None = None) -> bool:
    """평일 09:00–15:40 KST(동시호가 종가까지). 휴장일은 네이버 marketStatus로 걸러진다."""
    now = now or datetime.now(KST)
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (15, 40)


def refresh_quotes(conn: sqlite3.Connection, codes: set[str], fetch=None, ttl: int = QUOTE_TTL, force: bool = False) -> bool:
    """장중이고 마지막 갱신이 30분 넘었으면 네이버 실시간 시세로 portfolio_quotes를 덮어쓴다. 받으러 갔으면 True.

    조회(summary·history)는 이 함수를 부르지 않는다 — 갱신은 POST /quotes/refresh와 pfintraday 작업만.
    조회 실패 시 기존 값을 유지하되, 응답의 quoted_at(종목별 시세 시각)이 그대로 남아 화면이 오래된 시세임을 드러낸다.
    """
    if not codes or not (force or market_hours()):      # force = 화면의 '시세 갱신' 버튼(장 시간·TTL 무시)
        return False
    q = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT stock_code, fetched_at FROM portfolio_quotes WHERE stock_code IN ({q})", tuple(codes)).fetchall()
    fresh = {r["stock_code"] for r in rows if r["fetched_at"] and time.time() - r["fetched_at"] < ttl}
    if fresh >= codes and not force:
        return False
    if fetch is None:
        from pipeline.quotes import fetch_quotes as fetch
    now = time.time()
    for qt in fetch(sorted(codes)):
        if qt.get("stock_code") in codes and qt.get("price"):
            conn.execute("INSERT OR REPLACE INTO portfolio_quotes VALUES (?,?,?,?,?,?)",
                         (qt["stock_code"], qt["price"], qt.get("change_pct"), qt.get("market_status"), qt.get("traded_at"), now))
    conn.commit()
    return True


def _live(conn: sqlite3.Connection, codes: set[str], prices: dict[str, list[tuple[str, float]]]) -> dict[str, dict]:
    """종가보다 새 날짜의 장중 시세만(16:10 종가가 들어오면 자동으로 종가가 이긴다)."""
    if not codes:
        return {}
    q = ",".join("?" * len(codes))
    out = {}
    for r in conn.execute(f"SELECT * FROM portfolio_quotes WHERE stock_code IN ({q})", tuple(codes)):
        day = (r["traded_at"] or "")[:10]
        ser = prices.get(r["stock_code"], [])
        if r["price"] and day and (not ser or day > ser[-1][0]):
            out[r["stock_code"]] = {"date": day, "price": float(r["price"]), "change_pct": r["change_pct"], "at": r["traded_at"]}
    return out


def _with_live(prices: dict[str, list[tuple[str, float]]], live: dict[str, dict]) -> dict[str, list[tuple[str, float]]]:
    return {code: ser + ([(live[code]["date"], live[code]["price"])] if code in live else []) for code, ser in prices.items()}


def last_close_before(conn: sqlite3.Connection, code: str, day: str) -> float | None:
    row = conn.execute("SELECT close FROM stock_prices WHERE stock_code=? AND trade_date<=? AND close IS NOT NULL "
                       "ORDER BY trade_date DESC LIMIT 1", (code, day)).fetchone()
    return float(row["close"]) if row else None


def add_transaction(conn: sqlite3.Connection, tx: dict, fund_shortfall: bool = True) -> int:
    """거래 추가. 체결가 미입력은 그날 이전 마지막 종가. 매수 현금 부족 시 fund_shortfall이면 부족분 입금을 먼저 기록."""
    gid = group_id(conn)
    tx = {**tx, "note": tx.get("note") or ""}
    if tx["kind"] in ("buy", "sell"):
        if not tx.get("stock_code"):
            raise LedgerError("종목을 선택하세요.")
        if not conn.execute("SELECT 1 FROM companies WHERE stock_code=?", (tx["stock_code"],)).fetchone():
            raise LedgerError("알 수 없는 종목입니다.")
        if not tx.get("price"):
            tx["price"] = last_close_before(conn, tx["stock_code"], tx["trade_date"])
            if not tx["price"]:
                raise LedgerError("체결가를 입력하세요(저장된 종가 없음).")
    else:
        tx["stock_code"], tx["price"] = None, None
    existing = _txs(conn, gid)
    if tx.pop("sell_all", False):
        pos = replay([t for t in existing if t["trade_date"] <= tx["trade_date"]]).positions.get(tx["stock_code"])
        if not pos:
            raise LedgerError(f"{tx['trade_date']}에 보유하지 않은 종목입니다.")
        tx["amount"] = pos.qty * tx["price"]
    pending = []
    if tx["kind"] == "buy" and fund_shortfall:
        cash = replay([t for t in existing if t["trade_date"] <= tx["trade_date"]]).cash
        if tx["amount"] > cash + EPS:
            pending.append({"kind": "deposit", "amount": tx["amount"] - cash, "stock_code": None, "price": None,
                            "trade_date": tx["trade_date"], "note": "매수 부족분 자동 입금"})
    pending.append(tx)
    next_id = (max((t["id"] for t in existing), default=0) + 1)
    ledger = replay(existing + [{**p, "id": next_id + k} for k, p in enumerate(pending)])   # 저장 전에 전체 원장 검증
    new_id = 0
    for p in pending:
        new_id = conn.execute("INSERT INTO portfolio_transactions (group_id, trade_date, kind, stock_code, amount, price, note) "
                              "VALUES (?,?,?,?,?,?,?)",
                              (gid, p["trade_date"], p["kind"], p["stock_code"], p["amount"], p["price"], p["note"])).lastrowid
    _sync_members(conn, gid, ledger)
    conn.commit()
    return new_id


def delete_transaction(conn: sqlite3.Connection, tx_id: int) -> None:
    gid = group_id(conn)
    rest = [t for t in _txs(conn, gid) if t["id"] != tx_id]
    ledger = replay(rest)   # 남은 원장이 깨지면 LedgerError
    conn.execute("DELETE FROM portfolio_transactions WHERE id=? AND group_id=?", (tx_id, gid))
    _sync_members(conn, gid, ledger)
    conn.commit()


def transactions(conn: sqlite3.Connection) -> list[dict]:
    """거래 내역 — 금액·수량 없이."""
    gid = group_id(conn)
    txs = _txs(conn, gid)
    names = _names(conn, {t["stock_code"] for t in txs if t["stock_code"]})
    return [{"id": t["id"], "trade_date": t["trade_date"], "kind": t["kind"], "stock_code": t["stock_code"],
             "name": names.get(t["stock_code"], t["stock_code"]) if t["stock_code"] else None, "price": t["price"]}
            for t in reversed(txs)]


def _priced(conn: sqlite3.Connection, txs: list[dict], ledger: Ledger):
    """종가 시계열 + 저장된 보유 종목 장중 시세(종가보다 새 날짜만). 읽기 전용 — 네트워크·쓰기 없음."""
    codes = {t["stock_code"] for t in txs if t["stock_code"]}
    prices = _prices(conn, codes, txs[0]["trade_date"])
    live = _live(conn, set(ledger.positions), prices)
    return _with_live(prices, live), live


def refresh_now(conn: sqlite3.Connection, force: bool = True) -> dict:
    """보유 종목 시세를 다시 받는다. force=False면 장 시간·30분 TTL을 지킨다(화면 진입·주기 갱신).

    받은 시각을 돌려준다(실패하면 이전 시각 그대로 — 화면이 오래된 시세임을 보인다). refreshed = 실제로 받으러 갔는지.
    """
    held = set(replay(_txs(conn, group_id(conn))).positions)
    refreshed = refresh_quotes(conn, held, force=force)
    if not held:
        return {"quoted_at": None, "count": 0, "refreshed": False}
    q = ",".join("?" * len(held))
    row = conn.execute(f"SELECT max(traded_at) at, count(*) n FROM portfolio_quotes WHERE stock_code IN ({q})", tuple(held)).fetchone()
    return {"quoted_at": row["at"], "count": row["n"], "refreshed": refreshed}


def history(conn: sqlite3.Connection) -> list[dict]:
    gid = group_id(conn)
    txs = _txs(conn, gid)
    if not txs:
        return []
    prices, _ = _priced(conn, txs, replay(txs))
    return valuation(txs, prices)


def summary(conn: sqlite3.Connection) -> dict:
    """현황 — 비율·가격만."""
    gid = group_id(conn)
    txs = _txs(conn, gid)
    if not txs:
        return {"as_of": None, "total_return_pct": None, "day_return_pct": None, "cash_weight_pct": None, "holdings": [], "quoted_at": None,
                "realized_pct": None, "unrealized_pct": None, "closed": []}
    ledger = replay(txs)
    prices, live = _priced(conn, txs, ledger)
    hist = valuation(txs, prices)
    names = _names(conn, set(ledger.positions))
    entries = entry_weights(txs, prices)
    rows, total, unrealized = [], ledger.cash, 0.0
    for code, pos in ledger.positions.items():
        ser = prices.get(code, [])
        close = ser[-1][1] if ser else None
        prev = ser[-2][1] if len(ser) > 1 else None
        value = pos.qty * (close if close is not None else pos.avg)
        total += value
        unrealized += value - pos.qty * pos.avg
        lv = live.get(code)
        day_change = lv["change_pct"] if lv and lv["change_pct"] is not None else \
            round((close / prev - 1) * 100, 2) if close is not None and prev else None   # 장중은 거래소 전일 종가 대비
        rows.append({"code": code, "name": names.get(code, code), "value": value, "avg_price": round(pos.avg, 2),
                     "last_close": close, "last_date": ser[-1][0] if ser else None, "entry_date": pos.entry_date,
                     "price_source": "live" if lv else "close", "quoted_at": lv["at"] if lv else None,
                     "return_pct": round((close / pos.avg - 1) * 100, 2) if close is not None else None,
                     "day_change_pct": day_change, "entry_weight_pct": entries.get(code)})
    holdings = []
    for r in sorted(rows, key=lambda r: -r["value"]):
        weight = r.pop("value") / total * 100 if total > EPS else None
        holdings.append({**r, "weight_pct": round(weight, 2) if weight is not None else None})
    return {"as_of": hist[-1]["date"] if hist else None,
            "total_return_pct": hist[-1]["cum_return_pct"] if hist else None,
            "day_return_pct": hist[-1]["day_return_pct"] if hist else None,
            "cash_weight_pct": round(ledger.cash / total * 100, 2) if total > EPS else None,
            "holdings": holdings,
            "quoted_at": max((v["at"] for v in live.values()), default=None),
            **_realized_summary(conn, txs, unrealized)}


def _realized_summary(conn: sqlite3.Connection, txs: list[dict], unrealized: float) -> dict:
    """실현·미실현 손익을 원금(순입금) 대비 %로 — 원화는 내보내지 않는다. 계좌 수익률(TWR)과는 별개의 단순 비율."""
    closed, gain = realized_trades(txs)
    principal = sum(t["amount"] for t in txs if t["kind"] == "deposit") - sum(t["amount"] for t in txs if t["kind"] == "withdraw")
    names = _names(conn, {c["code"] for c in closed})
    pct = (lambda v: round(v / principal * 100, 2)) if principal > EPS else (lambda v: None)
    return {"realized_pct": pct(gain), "unrealized_pct": pct(unrealized),
            "closed": [{**c, "name": names.get(c["code"], c["code"])} for c in reversed(closed)]}

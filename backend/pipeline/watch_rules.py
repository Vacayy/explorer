"""종목 묶음(포트폴리오·관심)과 기술적 감시 규칙의 일일 평가 (docs/specs/portfolio-watch.md, D-185).

- 묶음 하나에 종류(watch|portfolio)만 다르다. 멤버는 종목 + 선택 입력(수량·매수가·확신도·목표가·논지).
- 규칙은 묶음 기본(stock_code NULL) + 종목별. 같은 strategy_id는 종목 규칙이 기본을 덮는다.
- 평가는 `market_analysis.strategies.evaluate_strategy`(순수 계산, 모델 호출 0)로 하고 (규칙, 종목, 기준일)마다
  한 번만 저장한다. `unavailable`은 실패로 바꾸지 않는다.
- 신호 = 전날 pass가 아니었다가 오늘 pass로 바뀐 전이.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date

from database import get_connection
from pipeline.market_analysis.strategies import catalog, evaluate_strategy, history_requirement, normalize_condition
from pipeline.ops import record_run

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'watch' CHECK(kind IN ('watch', 'portfolio')),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS stock_group_members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL REFERENCES stock_groups(id) ON DELETE CASCADE,
    stock_code   TEXT NOT NULL,
    quantity     REAL,
    avg_price    REAL,
    bought_at    TEXT,
    conviction   INTEGER CHECK(conviction BETWEEN 1 AND 5),
    target_price INTEGER,
    thesis       TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(group_id, stock_code)
);
CREATE TABLE IF NOT EXISTS watch_rules (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id           INTEGER NOT NULL REFERENCES stock_groups(id) ON DELETE CASCADE,
    stock_code         TEXT,                          -- NULL = 묶음 기본 규칙
    strategy_id        TEXT NOT NULL,
    params_json        TEXT NOT NULL DEFAULT '{}',
    within_days        INTEGER NOT NULL DEFAULT 1,
    source_strategy_id TEXT,                          -- 저장 전략에서 복사한 경우
    source_version     INTEGER,
    created_at         TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watch_evaluations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL,
    stock_code   TEXT NOT NULL,
    rule_id      INTEGER NOT NULL,
    as_of        TEXT NOT NULL,
    status       TEXT NOT NULL,                       -- pass | fail | unavailable
    value        REAL,
    reference    REAL,
    signal_date  TEXT,
    reason       TEXT,
    evaluated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(rule_id, stock_code, as_of)
);
CREATE INDEX IF NOT EXISTS idx_watch_eval_group_date ON watch_evaluations(group_id, as_of);
"""

DEFAULT_WATCH_GROUP_NAME = "관심 종목"  # 기본 관심 묶음 — 이름으로 찾는다(레거시 watchlist 이관 대상)


def connect() -> sqlite3.Connection:
    """단일 진입점 — 테스트는 이 함수만 바꿔 임시 DB를 쓴다."""
    return get_connection()


def strategy_labels() -> dict[str, str]:
    return {item["id"]: item["label"] for item in catalog()}


def rule_condition(rule: sqlite3.Row | dict) -> dict:
    return {"strategy_id": rule["strategy_id"], "params": json.loads(rule["params_json"] or "{}"),
            "within_days": rule["within_days"]}


def validate_rule(rule: dict) -> dict:
    """ValueError를 그대로 올린다 — 라우터가 400으로 바꾼다."""
    normalized = normalize_condition({"strategy_id": rule["strategy_id"], "params": rule.get("params") or {},
                                      "within_days": rule.get("within_days", 1)})
    if normalized["strategy_id"].startswith("rank_"):
        raise ValueError("순위 조건은 종목 묶음 감시에 쓸 수 없습니다.")
    return normalized


def effective_rules(conn: sqlite3.Connection, group_id: int, stock_code: str) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM watch_rules WHERE group_id=? AND (stock_code IS NULL OR stock_code=?) "
                        "ORDER BY stock_code IS NOT NULL, id", (group_id, stock_code)).fetchall()
    chosen: dict[str, sqlite3.Row] = {}
    for row in rows:  # 기본 규칙 먼저, 종목 규칙이 같은 strategy_id를 덮는다
        chosen[row["strategy_id"]] = row
    return list(chosen.values())


def latest_trade_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(trade_date) d FROM stock_prices").fetchone()
    return row["d"] if row and row["d"] else None


def load_rows(conn: sqlite3.Connection, stock_code: str, as_of: str, sessions: int, start_date: str | None) -> list[dict]:
    if start_date:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume, shares FROM stock_prices "
                            "WHERE stock_code=? AND trade_date<=? AND trade_date>=? ORDER BY trade_date",
                            (stock_code, as_of, start_date)).fetchall()
    else:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume, shares FROM stock_prices "
                            "WHERE stock_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT ?",
                            (stock_code, as_of, sessions + 5)).fetchall()[::-1]
    return [{"date": r["trade_date"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"], "shares": r["shares"]} for r in rows]


def evaluate_group(conn: sqlite3.Connection, group_id: int, as_of: str | None = None, force: bool = False) -> dict:
    as_of = as_of or latest_trade_date(conn)
    summary = {"group_id": group_id, "as_of": as_of, "evaluated": 0, "passed": 0, "unavailable": 0, "skipped": 0}
    if not as_of:
        summary["error"] = "저장된 시세가 없습니다."
        return summary
    members = conn.execute("SELECT stock_code FROM stock_group_members WHERE group_id=? ORDER BY id", (group_id,)).fetchall()
    for member in members:
        code = member["stock_code"]
        for rule in effective_rules(conn, group_id, code):
            if not force and conn.execute("SELECT 1 FROM watch_evaluations WHERE rule_id=? AND stock_code=? AND as_of=?",
                                          (rule["id"], code, as_of)).fetchone():
                summary["skipped"] += 1
                continue
            condition = rule_condition(rule)
            try:
                need = history_requirement(condition, as_of)
                rows = load_rows(conn, code, as_of, need["sessions"], need["start_date"])
                result = evaluate_strategy(rows, condition)
            except ValueError as exc:
                result = {"status": "unavailable", "value": None, "reference": None, "date": None, "reason": f"invalid_condition:{exc}"}
            conn.execute("INSERT OR REPLACE INTO watch_evaluations (group_id, stock_code, rule_id, as_of, status, value, reference, signal_date, reason) "
                         "VALUES (?,?,?,?,?,?,?,?,?)",
                         (group_id, code, rule["id"], as_of, result["status"], result.get("value"), result.get("reference"),
                          result.get("date"), result.get("reason")))
            summary["evaluated"] += 1
            if result["status"] == "pass":
                summary["passed"] += 1
            elif result["status"] == "unavailable":
                summary["unavailable"] += 1
    conn.commit()
    return summary


def evaluate_all(as_of: str | None = None, force: bool = False) -> dict:
    started = time.monotonic()
    conn = connect()
    try:
        groups = [r["id"] for r in conn.execute("SELECT id FROM stock_groups ORDER BY id").fetchall()]
        summaries = [evaluate_group(conn, gid, as_of, force) for gid in groups]
    finally:
        conn.close()
    total = {"groups": len(summaries), "as_of": summaries[0]["as_of"] if summaries else as_of,
             **{k: sum(s[k] for s in summaries) for k in ("evaluated", "passed", "unavailable", "skipped")}}
    status = "ok" if summaries and not any(s.get("error") for s in summaries) else ("skipped" if not summaries else "error")
    record_run("watch_rules", status, " · ".join(f"{k} {v}" for k, v in total.items()), int((time.monotonic() - started) * 1000))
    return total


def signals(conn: sqlite3.Connection, group_id: int, days: int = 30, stock_code: str | None = None) -> list[dict]:
    """pass 전이 목록(최신 먼저). 전날 평가가 없어도 첫 pass는 전이로 본다."""
    rows = conn.execute(
        "SELECT e.stock_code, e.rule_id, e.as_of, e.status, e.value, e.reference, e.signal_date, r.strategy_id, r.params_json, r.within_days "
        "FROM watch_evaluations e JOIN watch_rules r ON r.id=e.rule_id WHERE e.group_id=? " + ("AND e.stock_code=? " if stock_code else "") +
        "ORDER BY e.stock_code, e.rule_id, e.as_of", (group_id, stock_code) if stock_code else (group_id,)).fetchall()
    labels = strategy_labels()
    out, previous = [], {}
    for row in rows:
        key = (row["stock_code"], row["rule_id"])
        before = previous.get(key)
        if row["status"] == "pass" and before != "pass":
            out.append({"stock_code": row["stock_code"], "rule_id": row["rule_id"], "as_of": row["as_of"],
                        "strategy_id": row["strategy_id"], "label": labels.get(row["strategy_id"], row["strategy_id"]),
                        "params": json.loads(row["params_json"] or "{}"), "value": row["value"], "reference": row["reference"],
                        "signal_date": row["signal_date"]})
        previous[key] = row["status"]
    if days:
        recent = [as_of for as_of in sorted({r["as_of"] for r in rows}, reverse=True)[:days]]
        out = [s for s in out if s["as_of"] in recent]
    return sorted(out, key=lambda s: (s["as_of"], s["stock_code"]), reverse=True)


def default_watch_group_id(conn: sqlite3.Connection, create: bool = True) -> int | None:
    """기본 관심 묶음(이름 '관심 종목', 종류 watch) — 기업 화면 ★·논지 쓰기가 여기로 간다. 없으면 만든다."""
    row = conn.execute("SELECT id FROM stock_groups WHERE name=? AND kind='watch' ORDER BY id LIMIT 1",
                       (DEFAULT_WATCH_GROUP_NAME,)).fetchone()
    if row:
        return row["id"]
    if not create:
        return None
    group_id = conn.execute("INSERT INTO stock_groups (name, kind, note) VALUES (?, 'watch', ?)",
                            (DEFAULT_WATCH_GROUP_NAME, "기본 관심 묶음 — 기업 화면의 ★가 이 묶음에 넣고 뺍니다")).lastrowid
    conn.commit()
    return group_id


def watched(conn: sqlite3.Connection) -> dict[str, str]:
    """관심 종목 = 모든 관심(watch) 묶음 멤버의 합집합. 종목코드 → 회사명(먼저 넣은 순)."""
    rows = conn.execute(
        "SELECT m.stock_code, MAX(c.corp_name) name FROM stock_group_members m JOIN stock_groups g ON g.id=m.group_id "
        "LEFT JOIN companies c ON c.stock_code=m.stock_code WHERE g.kind='watch' GROUP BY m.stock_code ORDER BY MIN(m.id)").fetchall()
    return {r["stock_code"]: r["name"] or r["stock_code"] for r in rows}


def watch_thesis(conn: sqlite3.Connection, stock_code: str) -> sqlite3.Row | None:
    """종목의 관심 논지·확신도·목표가. 논지가 있는 멤버 → 기본 묶음 → 오래된 묶음 순."""
    return conn.execute(
        "SELECT m.thesis, m.conviction, m.target_price FROM stock_group_members m JOIN stock_groups g ON g.id=m.group_id "
        "WHERE g.kind='watch' AND m.stock_code=? ORDER BY (m.thesis IS NULL OR m.thesis=''), (g.name=?) DESC, g.id LIMIT 1",
        (stock_code, DEFAULT_WATCH_GROUP_NAME)).fetchone()


MIGRATED_FIELDS = ("conviction", "target_price", "thesis")


def migrate_watchlist(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """레거시 watchlist → 기본 관심 묶음. 멱등: 없는 종목은 넣고, 있는 종목은 묶음 쪽 빈 칸만 레거시 값으로 채운다.

    `dry_run`이면 아무것도 쓰지 않고 계획만 돌려준다. watchlist 테이블은 지우지 않는다.
    """
    group_id = default_watch_group_id(conn, create=False)
    legacy = conn.execute("SELECT stock_code, corp_name, conviction, target_price, thesis FROM watchlist ORDER BY id").fetchall()
    members = {r["stock_code"]: r for r in conn.execute(
        "SELECT stock_code, conviction, target_price, thesis FROM stock_group_members WHERE group_id=?", (group_id,)).fetchall()} if group_id else {}
    plan = {"group_id": group_id, "create_group": group_id is None, "legacy": len(legacy), "add": [], "fill": [], "same": [],
            "group_only": sorted(set(members) - {r["stock_code"] for r in legacy})}
    for row in legacy:
        member = members.get(row["stock_code"])
        if member is None:
            plan["add"].append({"stock_code": row["stock_code"], "name": row["corp_name"],
                                "fields": [f for f in MIGRATED_FIELDS if row[f] not in (None, "")]})
            continue
        fill = [f for f in MIGRATED_FIELDS if member[f] in (None, "") and row[f] not in (None, "")]
        plan["fill" if fill else "same"].append({"stock_code": row["stock_code"], "name": row["corp_name"], "fields": fill})
    if dry_run:
        return plan
    group_id = plan["group_id"] = default_watch_group_id(conn)
    by_code = {r["stock_code"]: r for r in legacy}
    for item in plan["add"]:
        row = by_code[item["stock_code"]]
        conn.execute("INSERT OR IGNORE INTO stock_group_members (group_id, stock_code, conviction, target_price, thesis) VALUES (?,?,?,?,?)",
                     (group_id, row["stock_code"], row["conviction"], row["target_price"], row["thesis"]))
    for item in plan["fill"]:
        row = by_code[item["stock_code"]]
        conn.execute(f"UPDATE stock_group_members SET {', '.join(f'{f}=?' for f in item['fields'])} WHERE group_id=? AND stock_code=?",
                     (*(row[f] for f in item["fields"]), group_id, row["stock_code"]))
    conn.commit()
    return plan


def today() -> str:
    return date.today().isoformat()

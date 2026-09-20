"""종목 묶음(포트폴리오·관심)과 감시 규칙 API (docs/specs/portfolio-watch.md, D-185).

계산은 pipeline/watch_rules.py, 모델 호출은 없다. 평가는 launchd(evaluate_watch_rules.py)와 수동 POST가 만든다.
"""
import json

from fastapi import APIRouter, HTTPException, Query

from models.groups import GroupCreate, GroupUpdate, MemberCreate, MemberUpdate, RulesPut
from pipeline import watch_rules as wr

router = APIRouter(prefix="/api/spine/groups", tags=["spine"])


def _group(conn, group_id: int):
    row = conn.execute("SELECT * FROM stock_groups WHERE id=?", (group_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "묶음을 찾을 수 없습니다.")
    return dict(row)


def _rule(row, labels) -> dict:
    return {"id": row["id"], "stock_code": row["stock_code"], "strategy_id": row["strategy_id"],
            "label": labels.get(row["strategy_id"], row["strategy_id"]), "params": json.loads(row["params_json"] or "{}"),
            "within_days": row["within_days"], "source_strategy_id": row["source_strategy_id"], "source_version": row["source_version"]}


def _rules(conn, group_id: int, labels) -> dict:
    rows = conn.execute("SELECT * FROM watch_rules WHERE group_id=? ORDER BY id", (group_id,)).fetchall()
    out = {"default": [], "members": {}}
    for row in rows:
        item = _rule(row, labels)
        if row["stock_code"] is None:
            out["default"].append(item)
        else:
            out["members"].setdefault(row["stock_code"], []).append(item)
    return out


def _last_as_of(conn, group_id: int) -> str | None:
    row = conn.execute("SELECT MAX(as_of) d FROM watch_evaluations WHERE group_id=?", (group_id,)).fetchone()
    return row["d"] if row and row["d"] else None


def _member(conn, group: dict, row, last_as_of: str | None, labels) -> dict:
    code = row["stock_code"]
    company = conn.execute("SELECT corp_name, market, sector FROM companies WHERE stock_code=?", (code,)).fetchone()
    prices = conn.execute("SELECT trade_date, close, market_cap FROM stock_prices WHERE stock_code=? ORDER BY trade_date DESC LIMIT 2", (code,)).fetchall()
    close = prices[0]["close"] if prices else None
    previous = prices[1]["close"] if len(prices) > 1 else None
    change_pct = (close - previous) / previous * 100 if close is not None and previous else None
    hits = conn.execute("SELECT e.rule_id, e.value, e.reference, e.signal_date, r.strategy_id FROM watch_evaluations e JOIN watch_rules r ON r.id=e.rule_id "
                        "WHERE e.group_id=? AND e.stock_code=? AND e.as_of=? AND e.status='pass' ORDER BY e.rule_id",
                        (group["id"], code, last_as_of)).fetchall() if last_as_of else []
    unavailable = conn.execute("SELECT COUNT(*) n FROM watch_evaluations WHERE group_id=? AND stock_code=? AND as_of=? AND status='unavailable'",
                               (group["id"], code, last_as_of)).fetchone()["n"] if last_as_of else 0
    item = {**dict(row), "name": company["corp_name"] if company else code, "market": company["market"] if company else None,
            "close": close, "change_pct": change_pct, "market_cap": prices[0]["market_cap"] if prices else None,
            "price_date": prices[0]["trade_date"] if prices else None,
            "rule_count": len(wr.effective_rules(conn, group["id"], code)),
            "signals": [{"rule_id": h["rule_id"], "strategy_id": h["strategy_id"], "label": labels.get(h["strategy_id"], h["strategy_id"]),
                         "value": h["value"], "reference": h["reference"], "signal_date": h["signal_date"]} for h in hits],
            "unavailable": unavailable, "pnl": None, "return_pct": None}
    if group["kind"] == "portfolio" and row["quantity"] and row["avg_price"] and close is not None:
        item["pnl"] = (close - row["avg_price"]) * row["quantity"]
        item["return_pct"] = (close - row["avg_price"]) / row["avg_price"] * 100
    return item


def _detail(conn, group_id: int) -> dict:
    group = _group(conn, group_id)
    labels = wr.strategy_labels()
    last_as_of = _last_as_of(conn, group_id)
    members = [_member(conn, group, row, last_as_of, labels) for row in
               conn.execute("SELECT * FROM stock_group_members WHERE group_id=? ORDER BY id", (group_id,)).fetchall()]
    latest = wr.latest_trade_date(conn)
    return {**group, "members": members, "rules": _rules(conn, group_id, labels), "last_as_of": last_as_of,
            "latest_trade_date": latest, "evaluation_pending": bool(latest) and latest != last_as_of,
            "today_signals": sum(len(m["signals"]) for m in members)}


@router.get("")
def list_groups():
    conn = wr.connect()
    out = []
    for row in conn.execute("SELECT * FROM stock_groups ORDER BY id").fetchall():
        group = dict(row)
        last_as_of = _last_as_of(conn, group["id"])
        group["member_count"] = conn.execute("SELECT COUNT(*) n FROM stock_group_members WHERE group_id=?", (group["id"],)).fetchone()["n"]
        group["rule_count"] = conn.execute("SELECT COUNT(*) n FROM watch_rules WHERE group_id=?", (group["id"],)).fetchone()["n"]
        group["last_as_of"] = last_as_of
        group["today_signals"] = len([s for s in wr.signals(conn, group["id"], days=1) if s["as_of"] == last_as_of]) if last_as_of else 0
        out.append(group)
    latest = wr.latest_trade_date(conn)
    legacy = conn.execute("SELECT COUNT(*) n FROM watchlist").fetchone()["n"]
    migrated = conn.execute("SELECT 1 FROM stock_groups WHERE name=? AND kind='watch'", (wr.LEGACY_GROUP_NAME,)).fetchone() is not None
    conn.close()
    return {"items": out, "latest_trade_date": latest, "legacy_watchlist": {"count": legacy, "migrated": migrated}}


@router.post("", status_code=201)
def create_group(body: GroupCreate):
    conn = wr.connect()
    group_id = conn.execute("INSERT INTO stock_groups (name, kind, note) VALUES (?,?,?)", (body.name, body.kind, body.note)).lastrowid
    conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.get("/{group_id}")
def get_group(group_id: int):
    conn = wr.connect()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.patch("/{group_id}")
def update_group(group_id: int, body: GroupUpdate):
    conn = wr.connect()
    _group(conn, group_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        conn.execute(f"UPDATE stock_groups SET {', '.join(f'{k}=?' for k in fields)}, updated_at=datetime('now') WHERE id=?",
                     (*fields.values(), group_id))
        conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int):
    conn = wr.connect()
    _group(conn, group_id)
    conn.execute("DELETE FROM watch_evaluations WHERE group_id=?", (group_id,))
    conn.execute("DELETE FROM stock_groups WHERE id=?", (group_id,))
    conn.commit()
    conn.close()


@router.post("/{group_id}/members", status_code=201)
def add_member(group_id: int, body: MemberCreate):
    conn = wr.connect()
    _group(conn, group_id)
    if not conn.execute("SELECT 1 FROM companies WHERE stock_code=?", (body.stock_code,)).fetchone():
        conn.close()
        raise HTTPException(404, "등록되지 않은 종목 코드입니다.")
    conn.execute("INSERT OR IGNORE INTO stock_group_members (group_id, stock_code, quantity, avg_price, bought_at, conviction, target_price, thesis) "
                 "VALUES (?,?,?,?,?,?,?,?)", (group_id, body.stock_code, body.quantity, body.avg_price, body.bought_at,
                                              body.conviction, body.target_price, body.thesis))
    conn.execute("UPDATE stock_groups SET updated_at=datetime('now') WHERE id=?", (group_id,))
    conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.patch("/{group_id}/members/{stock_code}")
def update_member(group_id: int, stock_code: str, body: MemberUpdate):
    conn = wr.connect()
    _group(conn, group_id)
    fields = body.model_dump(exclude_unset=True)
    if fields:
        conn.execute(f"UPDATE stock_group_members SET {', '.join(f'{k}=?' for k in fields)} WHERE group_id=? AND stock_code=?",
                     (*fields.values(), group_id, stock_code))
        conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.delete("/{group_id}/members/{stock_code}")
def remove_member(group_id: int, stock_code: str):
    conn = wr.connect()
    _group(conn, group_id)
    conn.execute("DELETE FROM stock_group_members WHERE group_id=? AND stock_code=?", (group_id, stock_code))
    conn.execute("DELETE FROM watch_rules WHERE group_id=? AND stock_code=?", (group_id, stock_code))
    conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.put("/{group_id}/rules")
def put_rules(group_id: int, body: RulesPut):
    """기본 + 종목별 규칙 전체 교체. 내용이 같은 규칙은 id를 유지해 평가 이력이 끊기지 않는다."""
    conn = wr.connect()
    _group(conn, group_id)
    desired = {}
    try:
        for code, rules in [(None, body.default), *body.members.items()]:
            for rule in rules:
                normalized = wr.validate_rule(rule.model_dump())
                key = (code, normalized["strategy_id"], json.dumps(normalized["params"], sort_keys=True), normalized["within_days"])
                desired[key] = (rule.source_strategy_id, rule.source_version)
    except ValueError as exc:
        conn.close()
        raise HTTPException(400, f"조건이 올바르지 않습니다: {exc}")
    existing = {}
    for row in conn.execute("SELECT * FROM watch_rules WHERE group_id=?", (group_id,)).fetchall():
        existing[(row["stock_code"], row["strategy_id"], json.dumps(json.loads(row["params_json"] or "{}"), sort_keys=True), row["within_days"])] = row["id"]
    for key, rule_id in existing.items():
        if key not in desired:
            conn.execute("DELETE FROM watch_rules WHERE id=?", (rule_id,))
    for key, (source_id, source_version) in desired.items():
        if key not in existing:
            conn.execute("INSERT INTO watch_rules (group_id, stock_code, strategy_id, params_json, within_days, source_strategy_id, source_version) VALUES (?,?,?,?,?,?,?)",
                         (group_id, key[0], key[1], key[2], key[3], source_id, source_version))
    conn.execute("UPDATE stock_groups SET updated_at=datetime('now') WHERE id=?", (group_id,))
    conn.commit()
    detail = _detail(conn, group_id)
    conn.close()
    return detail


@router.post("/{group_id}/evaluate")
def evaluate(group_id: int, force: bool = Query(False), as_of: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    conn = wr.connect()
    _group(conn, group_id)
    summary = wr.evaluate_group(conn, group_id, as_of, force)
    detail = _detail(conn, group_id)
    conn.close()
    return {"summary": summary, "group": detail}


@router.get("/{group_id}/signals")
def group_signals(group_id: int, days: int = Query(30, ge=1, le=365), stock_code: str | None = None):
    conn = wr.connect()
    _group(conn, group_id)
    items = wr.signals(conn, group_id, days, stock_code)
    names = {r["stock_code"]: r["corp_name"] for r in conn.execute(
        "SELECT c.stock_code, c.corp_name FROM companies c JOIN stock_group_members m ON m.stock_code=c.stock_code WHERE m.group_id=?", (group_id,)).fetchall()}
    conn.close()
    return {"items": [{**s, "name": names.get(s["stock_code"], s["stock_code"])} for s in items]}


@router.get("/{group_id}/evaluations")
def group_evaluations(group_id: int, as_of: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    conn = wr.connect()
    _group(conn, group_id)
    as_of = as_of or _last_as_of(conn, group_id)
    labels = wr.strategy_labels()
    rows = conn.execute("SELECT e.*, r.strategy_id, r.params_json, r.within_days FROM watch_evaluations e JOIN watch_rules r ON r.id=e.rule_id "
                        "WHERE e.group_id=? AND e.as_of=? ORDER BY e.stock_code, e.rule_id", (group_id, as_of)).fetchall() if as_of else []
    conn.close()
    return {"as_of": as_of, "items": [{**dict(r), "label": labels.get(r["strategy_id"], r["strategy_id"]),
                                       "params": json.loads(r["params_json"] or "{}")} for r in rows]}


@router.post("/migrate-watchlist")
def migrate_watchlist():
    conn = wr.connect()
    result = wr.migrate_watchlist(conn)
    detail = _detail(conn, result["group_id"])
    conn.close()
    return {**result, "group": detail}

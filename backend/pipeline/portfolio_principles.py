"""포트폴리오 운용 원칙 감시 (D-227, docs/specs/portfolio-intelligence.md §5).

사용자가 자연어로 적은 운용 원칙("한 종목 30% 이하", "평단 대비 -15%면 정리 검토")을 저장할 때 모델이 한 번 수치 규칙으로
풀고(사용자가 확인 후 저장), 이후에는 모델 없이 계좌 상태(비중·수익률·현금·공통 변수 노출)와 대조해 어긴 순간 텔레그램으로
한 번 알린다. 풀렸다가 다시 어기면 또 알린다. 화면 배지는 없다(사용자 선택: 알림만).

프라이버시: 원칙 원문·상태는 로컬 DB(git 제외)에만. 응답·알림은 비율·가격만(D-212). 원장은 모델에 보내지 않는다 —
모델은 원칙 문장만 받는다.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_principles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,              -- 사용자가 적은 원칙 원문 (로컬 전용)
    rules_json  TEXT NOT NULL,              -- 확인된 수치 규칙 [{type, params}]
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS portfolio_principle_state (   -- 지금 어기고 있는 규칙(키) — 새로 들어설 때만 알림
    key    TEXT PRIMARY KEY,
    since  TEXT DEFAULT (datetime('now'))
);
"""

# type → (라벨, 매개변수 이름, 최소, 최대, 장중 점검 여부)
RULES: dict[str, tuple[str, str, float, float, bool]] = {
    "max_weight": ("보유 비중 상한", "pct", 1, 100, True),
    "max_entry_weight": ("신규 진입 비중 상한", "pct", 1, 100, False),
    "min_cash": ("현금 비중 하한", "pct", 0, 100, True),
    "max_cash": ("현금 비중 상한", "pct", 0, 100, False),
    "stop_loss": ("평단 대비 손실 한도", "pct", 0.5, 90, True),
    "take_profit": ("평단 대비 이익 실현 점검", "pct", 0.5, 1000, True),
    "day_drop": ("하루 하락 한도", "pct", 0.5, 30, True),
    "max_holdings": ("보유 종목 수 상한", "count", 1, 100, False),
    "max_exposure": ("공통 변수(테마) 노출 상한", "pct", 1, 100, False),
    "max_holding_days": ("보유 기간 점검", "days", 1, 3650, False),
    "account_drawdown": ("계좌 누적 손실 한도", "pct", 0.5, 90, False),
}

PARSE_SYSTEM = """너는 개인 투자자의 포트폴리오 운용 원칙 문장을 기계가 매일 점검할 수 있는 수치 규칙으로 옮긴다.
허용된 규칙 유형만 쓴다(설명은 request.json의 rule_types). 문장에 없는 숫자를 지어내지 마라.
- 비율은 % 숫자(30% → 30). 손실·하락 한도도 양수로 적는다(-15% → 15).
- 비중을 구분한다: "처음 들어갈 때·신규 진입·한 번에·초기 포지션은 N% 까지"는 max_entry_weight(첫 매수 한 번만 본다, 이후 나눠 사서 커지는 건 허용).
  "어떤 종목도 보유 비중이 N%를 넘지 않게·비중이 커지면 줄인다"처럼 보유 중 내내 지키는 상한만 max_weight. 애매하면 max_entry_weight를 쓰지 말고 unparsed로.
- 한 문장이 여러 규칙이면 여러 개로 나눈다.
- 허용 유형으로 옮길 수 없는 원칙(예: "실적이 꺾이면 판다", "뉴스에 흔들리지 않는다")은 rules에 넣지 말고 unparsed에 넣는다.
  긴 글이면 원칙·판단 기준이 되는 문장만 한 줄씩 짧게 정리하고(원문 표현을 살린다), 일화·인용·감상은 뺀다. 같은 내용은 한 번만.
- 애매해서 숫자가 없으면 unparsed로 보낸다."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    try:   # 확인 화면에서 보여준 '대화에서 참고하는 원칙' 목록 — 시스템이 원문을 어떻게 이해했는지 남긴다
        conn.execute("ALTER TABLE portfolio_principles ADD COLUMN notes_json TEXT")
    except sqlite3.OperationalError:
        pass


def _clean_notes(notes) -> list[str]:
    return [n.strip()[:500] for n in (notes or []) if isinstance(n, str) and n.strip()][:60]


def validate(rules: list) -> list[dict]:
    """허용 유형·매개변수 범위만 통과. 하나라도 틀리면 ValueError."""
    if not isinstance(rules, list) or len(rules) > 20:
        raise ValueError("규칙은 20개까지입니다.")
    out = []
    for rule in rules:
        kind = rule.get("type") if isinstance(rule, dict) else None
        if kind not in RULES:
            raise ValueError(f"지원하지 않는 규칙 유형: {kind}")
        _label, param, low, high, _live = RULES[kind]
        value = (rule.get("params") or {}).get(param)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"{RULES[kind][0]}: {param}은 {low}~{high} 사이 숫자여야 합니다.")
        out.append({"type": kind, "params": {param: int(value) if param in ("count", "days") else float(value)}})
    return out


def describe(rule: dict) -> str:
    """사람이 읽는 한 줄 — 화면 확인용."""
    kind, (param, value) = rule["type"], next(iter(rule["params"].items()))
    label = RULES[kind][0]
    unit = {"pct": "%", "count": "개", "days": "일"}[param]
    sign = "−" if kind in ("stop_loss", "day_drop", "account_drawdown") else ""
    return f"{label} {sign}{value:g}{unit}"


def parse(text: str, call=None) -> dict:
    """원칙 문장 → {rules, unparsed}. 모델 1회(haiku, 저장 전 사용자가 확인). 저장하지 않는다."""
    if call is None:
        from pipeline.market_analysis.model import structured_call
        call = lambda system, ctx, schema: structured_call(system, ctx, schema, budget=.05, timeout=60, model="haiku")[0]  # noqa: E731
    schema = {"type": "object", "required": ["rules", "unparsed"], "properties": {
        "rules": {"type": "array", "maxItems": 20, "items": {"type": "object", "required": ["type", "params"], "properties": {
            "type": {"type": "string", "enum": list(RULES)},
            "params": {"type": "object", "properties": {"pct": {"type": "number"}, "count": {"type": "integer"}, "days": {"type": "integer"}}}}}},
        "unparsed": {"type": "array", "maxItems": 60, "items": {"type": "string", "maxLength": 300}}}}
    context = {"text": text, "rule_types": {k: {"label": v[0], "param": v[1], "range": [v[2], v[3]]} for k, v in RULES.items()}}
    payload = call(PARSE_SYSTEM, context, schema)
    kept, dropped = [], [s for s in payload.get("unparsed", []) if isinstance(s, str)]
    for rule in payload.get("rules", []):
        try:
            kept += validate([rule])
        except ValueError as e:
            dropped.append(str(e))
    return {"rules": [{**r, "summary": describe(r)} for r in kept], "unparsed": dropped}


def add(conn: sqlite3.Connection, text: str, rules: list, notes: list | None = None) -> int:
    ensure_schema(conn)
    clean = validate(rules)
    if not clean and not _clean_notes(notes):
        raise ValueError("점검 규칙이나 참고 원칙이 하나는 있어야 합니다.")
    new_id = conn.execute("INSERT INTO portfolio_principles (text, rules_json, notes_json) VALUES (?, ?, ?)",
                          (text.strip(), json.dumps(clean), json.dumps(_clean_notes(notes), ensure_ascii=False))).lastrowid
    conn.commit()
    return new_id


def replace(conn: sqlite3.Connection, principle_id: int, text: str, rules: list, notes: list | None = None) -> bool:
    """다시 풀기 — 원문·규칙·참고 목록을 함께 바꾸고, 그 원칙의 위반 상태는 지운다(새 규칙 기준으로 다시 알림)."""
    ensure_schema(conn)
    clean = validate(rules)
    if not clean and not _clean_notes(notes):
        raise ValueError("점검 규칙이나 참고 원칙이 하나는 있어야 합니다.")
    changed = conn.execute("UPDATE portfolio_principles SET text=?, rules_json=?, notes_json=? WHERE id=?",
                           (text.strip(), json.dumps(clean), json.dumps(_clean_notes(notes), ensure_ascii=False), principle_id)).rowcount
    conn.execute("DELETE FROM portfolio_principle_state WHERE key LIKE ?", (f"{principle_id}:%",))
    conn.commit()
    return bool(changed)


def update_text(conn: sqlite3.Connection, principle_id: int, text: str) -> bool:
    """원문만 바꾼다(규칙·위반 상태 유지). 없는 id면 False."""
    ensure_schema(conn)
    changed = conn.execute("UPDATE portfolio_principles SET text=? WHERE id=?", (text.strip(), principle_id)).rowcount
    conn.commit()
    return bool(changed)


def remove(conn: sqlite3.Connection, principle_id: int) -> None:
    ensure_schema(conn)
    conn.execute("DELETE FROM portfolio_principles WHERE id=?", (principle_id,))
    conn.execute("DELETE FROM portfolio_principle_state WHERE key LIKE ?", (f"{principle_id}:%",))
    conn.commit()


def principles(conn: sqlite3.Connection) -> list[dict]:
    ensure_schema(conn)
    return [{"id": r["id"], "text": r["text"], "created_at": r["created_at"],
             "rules": [{**rule, "summary": describe(rule)} for rule in json.loads(r["rules_json"])],
             "notes": json.loads(r["notes_json"]) if r["notes_json"] else []}
            for r in conn.execute("SELECT * FROM portfolio_principles ORDER BY id")]


def violations(items: list[dict], summary: dict, exposure: dict | None = None, today: str | None = None,
               live_only: bool = False) -> list[dict]:
    """원칙 × 계좌 상태 → 어긴 것들. 순수 함수. key = 원칙id:규칙번호:대상 — 같은 키는 풀릴 때까지 한 번만 알린다."""
    out = []
    holdings = summary.get("holdings", [])
    today = today or date.today().isoformat()

    def hit(p, i, rule, target, message):
        out.append({"key": f"{p['id']}:{i}:{target}", "principle_id": p["id"], "principle": p["text"],
                    "rule": describe(rule), "message": message})

    for p in items:
        for i, rule in enumerate(p["rules"]):
            kind, value = rule["type"], next(iter(rule["params"].values()))
            if live_only and not RULES[kind][4]:
                continue
            if kind == "max_weight":
                for h in holdings:
                    if h["weight_pct"] is not None and h["weight_pct"] > value:
                        hit(p, i, rule, h["code"], f"{h['name']} 비중 {h['weight_pct']:.1f}% (상한 {value:g}%)")
            elif kind == "max_entry_weight":
                for h in holdings:
                    w = h.get("entry_weight_pct")
                    if w is not None and w > value:
                        hit(p, i, rule, f"{h['code']}:{h['entry_date']}", f"{h['name']} 신규 진입 비중 {w:.1f}% (상한 {value:g}%)")
            elif kind in ("min_cash", "max_cash"):
                cash = summary.get("cash_weight_pct")
                if cash is not None and (cash < value if kind == "min_cash" else cash > value):
                    hit(p, i, rule, "cash", f"현금 비중 {cash:.1f}% ({'하한' if kind == 'min_cash' else '상한'} {value:g}%)")
            elif kind == "stop_loss":
                for h in holdings:
                    if h["return_pct"] is not None and h["return_pct"] <= -value:
                        hit(p, i, rule, f"{h['code']}:{h['entry_date']}", f"{h['name']} 평단 대비 {h['return_pct']:+.1f}% (한도 −{value:g}%)")
            elif kind == "take_profit":
                for h in holdings:
                    if h["return_pct"] is not None and h["return_pct"] >= value:
                        hit(p, i, rule, f"{h['code']}:{h['entry_date']}", f"{h['name']} 평단 대비 {h['return_pct']:+.1f}% (점검 +{value:g}%)")
            elif kind == "day_drop":
                for h in holdings:
                    if h["day_change_pct"] is not None and h["day_change_pct"] <= -value:
                        hit(p, i, rule, f"{h['code']}:{today}", f"{h['name']} 전일 대비 {h['day_change_pct']:+.1f}% (한도 −{value:g}%)")
            elif kind == "max_holdings":
                if len(holdings) > value:
                    hit(p, i, rule, "count", f"보유 {len(holdings)}종목 (상한 {value:g}개)")
            elif kind == "max_exposure":
                for d in (exposure or {}).get("drivers", []):
                    if d["exposure_pct"] > value:
                        hit(p, i, rule, f"driver:{d['key']}", f"'{d['name']}' 노출 {d['exposure_pct']:.1f}% (상한 {value:g}%)")
            elif kind == "max_holding_days":
                for h in holdings:
                    days = (date.fromisoformat(today) - date.fromisoformat(h["entry_date"])).days
                    if days >= value:
                        hit(p, i, rule, f"{h['code']}:{h['entry_date']}", f"{h['name']} 보유 {days}일 (점검 {value:g}일)")
            elif kind == "account_drawdown":
                total = summary.get("total_return_pct")
                if total is not None and total <= -value:
                    hit(p, i, rule, "account", f"계좌 수익률 {total:+.1f}% (한도 −{value:g}%)")
    return out


def current(conn: sqlite3.Connection, summary: dict, exposure=None, today: str | None = None) -> dict:
    """지금 어기고 있는 규칙(화면 표시용, 읽기만) — 알림 상태와 같은 키로 '이미 알렸는지·언제부터'를 붙인다. 원문은 싣지 않는다."""
    ensure_schema(conn)
    items = principles(conn)
    if callable(exposure):
        exposure = exposure() if any(r["type"] == "max_exposure" for p in items for r in p["rules"]) else None
    since = {r["key"]: r["since"] for r in conn.execute("SELECT key, since FROM portfolio_principle_state")}
    return {"rules": sum(len(p["rules"]) for p in items),
            "items": [{"key": v["key"], "principle_id": v["principle_id"], "rule": v["rule"], "message": v["message"],
                       "alerted_since": since.get(v["key"])} for v in violations(items, summary, exposure, today)]}


def alert(conn: sqlite3.Connection, summary: dict, send, *, exposure=None, live_only: bool = False,
          today: str | None = None, dry_run: bool = False) -> int:
    """새로 어긴 규칙만 보낸다. 장중 점검(live_only)은 장중 규칙만 보고, 그 밖의 규칙 상태는 건드리지 않는다.

    exposure는 dict 또는 그것을 돌려주는 함수 — 공통 변수 계산은 무거워 노출 규칙이 있을 때만 부른다.
    """
    ensure_schema(conn)
    items = principles(conn)
    if not items:
        return 0
    if callable(exposure):
        exposure = exposure() if not live_only and any(r["type"] == "max_exposure" for p in items for r in p["rules"]) else None
    found = violations(items, summary, exposure, today, live_only)
    keys = {v["key"] for v in found}
    checked = {f"{p['id']}:{i}:" for p in items for i, r in enumerate(p["rules"]) if not live_only or RULES[r["type"]][4]}
    state = {r["key"] for r in conn.execute("SELECT key FROM portfolio_principle_state")}
    fresh = [v for v in found if v["key"] not in state]
    cleared = [k for k in state if k not in keys and any(k.startswith(prefix) for prefix in checked)]
    if dry_run:
        if fresh:
            send(_message(fresh))
        return len(fresh)
    if fresh and not send(_message(fresh)):
        raise RuntimeError("텔레그램 발송 실패")   # 상태를 기록하지 않아 다음 점검에서 다시 보낸다
    conn.executemany("INSERT OR IGNORE INTO portfolio_principle_state (key) VALUES (?)", [(v["key"],) for v in fresh])
    conn.executemany("DELETE FROM portfolio_principle_state WHERE key=?", [(k,) for k in cleared])
    conn.commit()
    return len(fresh)


def _message(found: list[dict]) -> str:
    lines = ["📏 <b>운용 원칙을 벗어났습니다</b>"]
    for v in found:
        lines.append(f"• {html.escape(v['message'])}\n  └ {html.escape(v['rule'])} — “{html.escape(v['principle'][:80])}”")
    return "\n".join(lines)

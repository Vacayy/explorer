"""종목 추적 위젯 (docs/specs/stock-tracker.md) — 종목 하나의 차트·기술적 신호·수급·이슈·내 원칙 조건을 한 카드로, 조건 충족 시 알림. LLM 0.

추적 대상의 단일 원천은 홈 배치의 `track.stock` 위젯이다(위젯을 빼면 추적·알림도 멈춘다).
알림은 portfolio_alerts.run에 편승하고 중복 방지 키(portfolio_alerts_sent)를 공유한다 — 보유와 추적이 겹쳐도 한 번만.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracker_conditions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT NOT NULL,
    role        TEXT NOT NULL,          -- entry(진입) | exit(손절·청산) | check(확인 항목)
    kind        TEXT NOT NULL,          -- price_below | price_above | close_below_ma | close_above_ma | manual
    level       REAL,                   -- 가격 조건의 기준가
    ma          INTEGER,                -- 이평선 조건의 N
    label       TEXT NOT NULL,
    note        TEXT,
    done        INTEGER DEFAULT 0,      -- manual 확인 여부
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tracker_cond ON tracker_conditions(stock_code);
"""
KINDS = {"price_below", "price_above", "close_below_ma", "close_above_ma", "manual"}
ROLES = {"entry", "exit", "check"}
WIDGET_ID = "track.stock"
DAY_STEP = 5.0
KEY_DISCLOSURE = ("대량보유", "소유상황", "잠정", "공급계약", "유상증자", "전환사채", "신주인수권", "자기주식", "합병", "분할")
STAMP_RE = re.compile(r"^\d{4}[.\-]\d{2}[.\-]\d{2}[ T]\d{2}:\d{2}")
TP_RE = re.compile(r"(목표주가|적정주가|목표가)[^0-9]{0,20}?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원")


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def tracked_codes(conn: sqlite3.Connection) -> list[str]:
    """홈 메뉴들(home_boards)에 놓인 종목 추적 위젯의 종목들(메뉴 순서대로, 중복 제거)"""
    try:
        rows = conn.execute("SELECT layout_json FROM home_boards ORDER BY sort, id").fetchall()
    except sqlite3.OperationalError:          # 메뉴 표가 없는 DB(테스트 등) = 추적 위젯 없음
        return []
    out: list[str] = []
    for row in rows:
        for it in json.loads(row[0]):
            code = (it.get("params") or {}).get("code") if it.get("widget") == WIDGET_ID else None
            if code and code not in out:
                out.append(str(code))
    return out


def _name(conn, code: str) -> str:
    r = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?", (code,)).fetchone()
    return r["corp_name"] if r else code


def _rows(conn, code: str, n: int = 260) -> list[sqlite3.Row]:
    return list(reversed(conn.execute("SELECT trade_date, open, high, low, close, volume FROM stock_prices WHERE stock_code=? AND close IS NOT NULL "
                                      "ORDER BY trade_date DESC LIMIT ?", (code, n)).fetchall()))


def _ma(closes: list[float], n: int, i: int | None = None) -> float | None:
    i = len(closes) - 1 if i is None else i
    return sum(closes[i - n + 1:i + 1]) / n if i + 1 >= n else None


def _price(conn, code: str, rows) -> dict:
    """장중 실시간 시세가 마지막 종가보다 새 날짜면 그것, 아니면 종가"""
    last = rows[-1] if rows else None
    q = conn.execute("SELECT price, change_pct, traded_at FROM portfolio_quotes WHERE stock_code=?", (code,)).fetchone()
    if q and q["price"] and last and (q["traded_at"] or "")[:10] > last["trade_date"]:
        return {"price": q["price"], "change_pct": q["change_pct"], "as_of": q["traded_at"], "source": "live"}
    if not last:
        return {"price": None, "change_pct": None, "as_of": None, "source": None}
    prev = rows[-2]["close"] if len(rows) > 1 else None
    return {"price": last["close"], "change_pct": round((last["close"] / prev - 1) * 100, 2) if prev else None, "as_of": last["trade_date"], "source": "close"}


def _chart(rows) -> dict:
    closes = [r["close"] for r in rows]
    tail = range(max(0, len(rows) - 120), len(rows))
    series = [{"t": rows[i]["trade_date"], "o": rows[i]["open"], "h": rows[i]["high"], "l": rows[i]["low"], "c": rows[i]["close"], "v": rows[i]["volume"],
               "ma20": _ma(closes, 20, i), "ma60": _ma(closes, 60, i), "ma120": _ma(closes, 120, i)} for i in tail]
    return {"series": series}


def _technicals(conn, code: str, rows) -> dict:
    from pipeline.portfolio_alerts import NOTABLE
    from pipeline.technical_scan import scan_company
    out: dict = {}
    try:
        from pipeline.investor_lens import _gather_trend
        g = _gather_trend(conn, code)
        t, vp, rg = g.get("technicals") or {}, g.get("volume_profile") or {}, g.get("regime") or {}
        out |= {k: t.get(k) for k in ("rsi14", "ma20_gap", "ma60_gap", "ma120_gap", "off_52w_high", "ret_1m", "ret_3m")}
        out |= {"overhead_pct": vp.get("overhead_pct"), "support_pct": vp.get("support_pct"), "rs": g.get("rs"),
                "regime": {"posture": rg.get("posture"), "reason": rg.get("reason")}}
    except Exception as e:  # noqa: BLE001 — 영역 단위 Partial
        out["error"] = f"{type(e).__name__}"
    vols = [r["volume"] or 0 for r in rows[-21:]]
    if len(vols) == 21 and sum(vols[:-1]):
        out["volume_ratio"] = round(vols[-1] / (sum(vols[:-1]) / 20), 2)
    try:
        sc = scan_company(conn, code, "kr", 5)
        out["signals"] = [{"date": s["date"], "label": s["label"], "id": s["id"]} for s in sc.get("signals", [])
                          if s["status"] == "pass" and (s["id"] in NOTABLE or s["category"] == "가격 구조")]
        out["signals_as_of"] = sc.get("as_of")
    except Exception as e:  # noqa: BLE001
        out["signals"], out["signals_error"] = [], type(e).__name__
    return out


def _flows(conn, code: str) -> dict | None:
    rows = conn.execute("SELECT * FROM investor_flows WHERE stock_code=? ORDER BY trade_date DESC LIMIT 20", (code,)).fetchall()
    if not rows:
        return None

    def won(rs, k):      # 순매수 주식 수 × 그날 종가 ≈ 금액(억원)
        return round(sum((r[k] or 0) * (r["close"] or 0) for r in rs) / 1e8, 1)
    out = {"as_of": rows[0]["trade_date"], "days": len(rows)}
    for k, lab in (("foreign_net", "foreign"), ("inst_net", "inst"), ("indiv_net", "indiv")):
        out[f"{lab}_5d"], out[f"{lab}_20d"] = won(rows[:5], k), won(rows, k)
    hr = [r["foreign_hold_ratio"] for r in rows if r["foreign_hold_ratio"] is not None]
    out["foreign_ratio"], out["foreign_ratio_chg"] = (hr[0], round(hr[0] - hr[-1], 2)) if hr else (None, None)
    out["daily"] = [{"d": r["trade_date"], "foreign": r["foreign_net"], "inst": r["inst_net"]} for r in reversed(rows)]
    return out


def _issues(conn, code: str, name: str) -> dict:
    corp = conn.execute("SELECT corp_code FROM companies WHERE stock_code=?", (code,)).fetchone()
    since14 = (date.today() - timedelta(days=14)).strftime("%Y%m%d")
    disc = [{"date": r["rcept_dt"], "title": (r["report_nm"] or "").strip(), "url": r["dart_url"],
             "key": any(k in (r["report_nm"] or "") for k in KEY_DISCLOSURE)}
            for r in conn.execute("SELECT rcept_dt, report_nm, dart_url FROM disclosures WHERE corp_code=? AND rcept_dt>=? ORDER BY rcept_dt DESC LIMIT 12",
                                  (corp["corp_code"] if corp else "", since14))]
    docs: dict[int, dict] = {}
    for r in conn.execute("""SELECT DISTINCT d.id, d.title, d.published_at, d.source_type, substr(d.markdown,1,200) head FROM entity_links el
            JOIN entities e ON e.id=el.entity_id JOIN raw_documents d ON d.id=el.doc_id
            WHERE el.link_type='stock' AND e.aliases=? AND d.published_at>=datetime('now','-7 days')""", (code,)):
        docs[r["id"]] = dict(r)
    for r in conn.execute("SELECT id, title, published_at, source_type, substr(markdown,1,200) head FROM raw_documents WHERE title LIKE ? "
                          "AND published_at>=datetime('now','-7 days')", (f"%{name}%",)):
        docs.setdefault(r["id"], dict(r))
    for d in docs.values():          # 텔레그램 글은 제목이 수집 시각('2026.10.20 11:24:29') — 본문으로 대신
        if not d["title"] or STAMP_RE.match(d["title"]):
            d["title"] = _headline(d["head"] or "") or d["title"]
    latest = sorted(docs.values(), key=lambda d: d["published_at"] or "", reverse=True)
    tps = []
    for r in conn.execute("SELECT id, published_at, title, markdown FROM raw_documents WHERE markdown LIKE ? AND published_at>=datetime('now','-30 days') "
                          "AND (markdown LIKE '%목표주가%' OR markdown LIKE '%적정주가%' OR markdown LIKE '%목표가%') ORDER BY published_at DESC LIMIT 20", (f"%{name}%",)):
        md = r["markdown"] or ""
        k = md.find(name)
        for m in TP_RE.finditer(md[max(0, k - 400):k + 1500] if k >= 0 else ""):
            v = int(m.group(2).replace(",", ""))
            if v >= 1000:
                tps.append({"date": (r["published_at"] or "")[:10], "value": v, "doc_id": r["id"], "title": r["title"]})
                break
    return {"disclosures": disc, "docs_7d": len(latest), "docs": [{k: d[k] for k in ("id", "title", "published_at", "source_type")} for d in latest[:5]],
            "target_prices": tps[:5]}


def _headline(text: str) -> str:
    """제목 없는 글의 한 줄 — 공시 알림 글이면 '보고서명 · 보고 후 지분', 아니면 시각·기업명 줄을 건너뛴 첫 줄"""
    lines = [ln.strip(" #*-·") for ln in text.splitlines() if ln.strip(" #*-·")]
    kv = {ln.split(":", 1)[0].strip(): ln.split(":", 1)[1].strip() for ln in lines if ":" in ln}
    if "보고서명" in kv:
        after = kv.get("보고후")
        return f"{kv['보고서명']}" + (f" · 보고 후 {after}" if after else "") + (f" · {kv['보고자']}" if kv.get("보고자") else "")
    return next((ln for ln in lines if not STAMP_RE.match(ln) and not ln.startswith("기업명")), "")[:80]


def conditions(conn, code: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM tracker_conditions WHERE stock_code=? ORDER BY role, id", (code,))]


def evaluate(cond: dict, price: float | None, rows) -> dict:
    """조건 상태 — met(충족) | not_met | pending(확인 대기) | unknown. 가격 조건은 거리(%)도"""
    closes = [r["close"] for r in rows]
    k, out = cond["kind"], {"status": "unknown", "distance_pct": None, "ref": None}
    if k == "manual":
        out["status"] = "met" if cond["done"] else "pending"
    elif k in ("price_below", "price_above") and price and cond["level"]:
        out["distance_pct"] = round((price / cond["level"] - 1) * 100, 1)
        out["status"] = "met" if (price <= cond["level"] if k == "price_below" else price >= cond["level"]) else "not_met"
    elif k in ("close_below_ma", "close_above_ma") and cond["ma"] and closes:
        ma = _ma(closes, int(cond["ma"]))
        if ma:
            out["ref"] = round(ma)
            out["distance_pct"] = round((closes[-1] / ma - 1) * 100, 1)
            out["status"] = "met" if (closes[-1] < ma if k == "close_below_ma" else closes[-1] > ma) else "not_met"
    return out


def read(conn, code: str) -> dict:
    ensure(conn)
    rows = _rows(conn, code)
    name = _name(conn, code)
    price = _price(conn, code, rows)
    conds = [c | evaluate(c, price["price"], rows) for c in conditions(conn, code)]
    return {"code": code, "name": name, **price, "last_close_date": rows[-1]["trade_date"] if rows else None,
            "chart": _chart(rows) if rows else {"series": []}, "technicals": _technicals(conn, code, rows) if rows else {},
            "flows": _flows(conn, code), "issues": _issues(conn, code, name), "conditions": conds}


# ── 알림 ─────────────────────────────────────────────────────────────────────

def _items(conn, mode: str, today: str, live: bool) -> list[tuple[str, str]]:
    from pipeline.portfolio_alerts import _bucket, _pct
    out = []
    for code in tracked_codes(conn):
        rows = _rows(conn, code)
        if not rows:
            continue
        name, price = _name(conn, code), _price(conn, code, rows)
        tag = f"🔭 <b>{html.escape(name)}</b>"
        if mode == "intraday" and live and price["source"] == "live":
            b = _bucket(price["change_pct"], DAY_STEP)
            if b:
                out.append((f"track-day:{today}:{code}:{b}", f"{tag} 추적 · 전일 대비 {_pct(price['change_pct'])} · 현재가 {price['price']:,.0f}"))
        for c in conditions(conn, code):
            intraday_kind = c["kind"] in ("price_below", "price_above")
            if c["kind"] == "manual" or (mode == "intraday") != intraday_kind:
                continue                                    # 가격 조건은 장중, 이평선 조건은 장 마감에
            if mode == "intraday" and price["source"] != "live":
                continue
            ev = evaluate(c, price["price"], rows)
            if ev["status"] == "met":
                icon = {"exit": "🛑", "entry": "✅"}.get(c["role"], "🔔")
                ref = f" (기준 {c['level']:,.0f})" if c["level"] else f" ({c['ma']}일선 {ev['ref']:,})" if ev.get("ref") else ""
                out.append((f"track-cond:{today}:{c['id']}", f"{icon} {tag} 조건 충족 · {html.escape(c['label'])}{ref} · 현재 {price['price']:,.0f}"))
    return out


def alert(conn, mode: str, send, today: str, now: datetime | None = None, dry_run: bool = False) -> int:
    """portfolio_alerts.run이 부른다 — 장중: 시세 갱신·급등락·가격 조건·공시 / 마감: 이평선 조건·기술적 신호·공시"""
    from pipeline import portfolio as pf
    from pipeline.portfolio_alerts import _send, new_disclosures, technical_signals
    ensure(conn)
    codes = tracked_codes(conn)
    if not codes:
        return 0
    live = mode == "intraday" and pf.market_hours(now)
    if live:
        pf.refresh_quotes(conn, set(codes), ttl=60)
    holdings = [{"code": c, "name": _name(conn, c)} for c in codes]
    sent = _send(conn, _items(conn, mode, today, live), "", send, dry_run)
    if mode == "close":
        sent += _send(conn, technical_signals(conn, holdings), "📐 <b>추적 종목 새 기술적 신호</b>", send, dry_run)
    sent += _send(conn, new_disclosures(holdings, today), "", send, dry_run)
    return sent

"""종목 추적 (docs/specs/stock-tracker.md) — 종목 하나의 차트·기술적 신호·수급·이슈·내 원칙 조건을 한 카드로, 조건 충족 시 알림. LLM 0.

추적 대상: 관심(watch) 묶음 멤버의 추적 표시(`stock_group_members.tracked=1`)만 읽는다(D-293, ia-redesign §10.2 ⑥).
옛 원천(홈 배치의 `track.stock` 위젯, D-267)은 더 읽지 않는다 — 배포 전에 scripts/migrate_tracking_to_groups.py로 옮겨 둬야 한다.
`widget_codes`·`source_diff`·`migrate_widget_tracking`은 그 일회 이관 스크립트만 쓴다.
국내 종목은 국내 시세(stock_prices·장중 portfolio_quotes), 미국 종목은 미국 일봉(us_prices)으로 판정한다.
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


def widget_codes(conn: sqlite3.Connection) -> list[str]:
    """옛 원천 — 홈 메뉴들(home_boards)에 놓인 종목 추적 위젯의 종목들(메뉴 순서대로, 중복 제거). 일회 이관 스크립트만 읽는다."""
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


def member_codes(conn: sqlite3.Connection) -> list[str]:
    """관심(watch) 묶음 멤버 중 추적을 켠 종목(묶음 순서·넣은 순서, 중복 제거) — 국내·미국 모두"""
    try:
        rows = conn.execute("SELECT m.stock_code FROM stock_group_members m JOIN stock_groups g ON g.id=m.group_id "
                            "WHERE g.kind='watch' AND m.tracked=1 ORDER BY g.id, m.id").fetchall()
    except sqlite3.OperationalError:          # 묶음 표·추적 컬럼이 없는 DB(테스트 등) = 추적 표시 없음
        return []
    return list(dict.fromkeys(str(r[0]) for r in rows))


def tracked_codes(conn: sqlite3.Connection) -> list[str]:
    """추적 대상 = 관심 종목의 추적 표시. 홈 위젯(옛 원천)은 읽지 않는다(2026-11-05 개편 3d)."""
    return member_codes(conn)


def source_diff(conn: sqlite3.Connection) -> dict:
    """두 원천 비교 — 일회 이관 스크립트의 확인용. widget_only가 남아 있으면 그 종목은 이관이 안 돼 알림이 오지 않는다."""
    widget, member = widget_codes(conn), member_codes(conn)
    return {"widget": widget, "member": member,
            "widget_only": [c for c in widget if c not in member], "member_only": [c for c in member if c not in widget]}


def migrate_widget_tracking(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """옛 원천(위젯) 종목을 기본 관심 묶음의 추적 표시로 복사한다. 멱등: 없으면 넣고(tracked=1), 있으면 표시만 켠다.

    위젯·home_boards는 건드리지 않는다. 추적 표시를 끄는 일은 하지 않는다(새 원천에만 있는 종목은 그대로).
    """
    from pipeline.watch_rules import default_watch_group_id
    group_id = default_watch_group_id(conn, create=False)
    members = {r["stock_code"]: r["tracked"] for r in conn.execute(
        "SELECT stock_code, tracked FROM stock_group_members WHERE group_id=?", (group_id,)).fetchall()} if group_id else {}
    plan = {"group_id": group_id, "create_group": group_id is None, "add": [], "mark": [], "same": []}
    for code in widget_codes(conn):
        key = "add" if code not in members else "same" if members[code] else "mark"
        plan[key].append({"stock_code": code, "name": _name(conn, code)})
    if dry_run:
        return plan
    group_id = plan["group_id"] = default_watch_group_id(conn)
    for item in plan["add"]:
        conn.execute("INSERT OR IGNORE INTO stock_group_members (group_id, stock_code, tracked) VALUES (?,?,1)", (group_id, item["stock_code"]))
    for item in plan["mark"]:
        conn.execute("UPDATE stock_group_members SET tracked=1 WHERE group_id=? AND stock_code=?", (group_id, item["stock_code"]))
    if plan["add"] or plan["mark"]:
        conn.execute("UPDATE stock_groups SET updated_at=datetime('now') WHERE id=?", (group_id,))
    conn.commit()
    return plan


def market(conn, code: str) -> str:
    """'kr'(companies) | 'us'(자료가 있는 미국 티커). 판정할 표가 없는 DB(테스트 등)는 국내로 본다."""
    if conn.execute("SELECT 1 FROM companies WHERE stock_code=?", (code,)).fetchone():
        return "kr"
    try:
        from pipeline.watch_rules import market_of
        return market_of(conn, code) or "kr"
    except sqlite3.OperationalError:
        return "kr"


def _name(conn, code: str) -> str:
    r = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?", (code,)).fetchone()
    if r:
        return r["corp_name"]
    try:   # 미국 티커 — 컨콜 팔로우 회사명
        r = conn.execute("SELECT company_name FROM transcript_follow WHERE ticker=?", (code,)).fetchone()
    except sqlite3.OperationalError:
        r = None
    return (r["company_name"] if r else None) or code


def _rows(conn, code: str, n: int = 260, mkt: str = "kr") -> list[sqlite3.Row]:
    table = "us_prices" if mkt == "us" else "stock_prices"
    return list(reversed(conn.execute(f"SELECT trade_date, open, high, low, close, volume FROM {table} WHERE stock_code=? AND close IS NOT NULL "
                                      "ORDER BY trade_date DESC LIMIT ?", (code, n)).fetchall()))


def money(v: float, mkt: str) -> str:
    """알림 문구의 가격 — 국내는 원 단위 정수, 미국은 달러 소수 2자리"""
    return f"${v:,.2f}" if mkt == "us" else f"{v:,.0f}"


def _ma(closes: list[float], n: int, i: int | None = None) -> float | None:
    i = len(closes) - 1 if i is None else i
    return sum(closes[i - n + 1:i + 1]) / n if i + 1 >= n else None


def _price(conn, code: str, rows, mkt: str = "kr") -> dict:
    """장중 실시간 시세가 마지막 종가보다 새 날짜면 그것, 아니면 종가. 미국은 실시간 시세가 없어 마지막 종가만."""
    last = rows[-1] if rows else None
    q = conn.execute("SELECT price, change_pct, traded_at FROM portfolio_quotes WHERE stock_code=?", (code,)).fetchone() if mkt == "kr" else None
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


def _technicals(conn, code: str, rows, mkt: str = "kr") -> dict:
    from pipeline.portfolio_alerts import NOTABLE
    from pipeline.technical_scan import scan_company
    out: dict = {}
    try:
        from pipeline.investor_lens import _gather_trend
        g = _gather_trend(conn, code, mkt)
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
        sc = scan_company(conn, code, mkt, 5)
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


def _issues(conn, code: str, name: str, mkt: str = "kr") -> dict:
    """국내: 공시 14일·피드 7일·목표주가 언급. 미국: 공시(DART)·원화 목표주가가 없어 피드 7일만."""
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
    for r in [] if mkt == "us" else conn.execute("SELECT id, published_at, title, markdown FROM raw_documents WHERE markdown LIKE ? AND published_at>=datetime('now','-30 days') "
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


def evaluate(cond: dict, price: float | None, rows, mkt: str = "kr") -> dict:
    """조건 상태 — met(충족) | not_met | pending(확인 대기) | unknown. 가격 조건은 거리(%)도. 이평선 값은 국내 원 단위, 미국 센트 단위"""
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
            out["ref"] = round(ma, 2) if mkt == "us" else round(ma)
            out["distance_pct"] = round((closes[-1] / ma - 1) * 100, 1)
            out["status"] = "met" if (closes[-1] < ma if k == "close_below_ma" else closes[-1] > ma) else "not_met"
    return out


def newly_met(cond: dict, ev: dict, price: dict, rows, mkt: str = "kr", today: str | None = None) -> bool:
    """오늘 새로 충족됐나 — 홈 › 내 종목의 조건 충족 알림 줄(ia-redesign §4.4). 충족 상태가 이어지는 날에는 False.

    확인 항목: 오늘(KST) 확인으로 바꿨으면. 가격·이평선: 지금은 충족인데 직전 기준(장중이면 마지막 종가, 아니면 전 거래일)엔 아니었으면.
    """
    if ev["status"] != "met":
        return False
    if cond["kind"] == "manual":
        stamp = cond.get("updated_at") or ""
        try:
            kst = (datetime.fromisoformat(stamp.replace(" ", "T")) + timedelta(hours=9)).date().isoformat()
        except ValueError:
            return False
        return kst == (today or (datetime.utcnow() + timedelta(hours=9)).date().isoformat())
    before = rows if price.get("source") == "live" else rows[:-1]
    if not before:
        return False
    return evaluate(cond, before[-1]["close"], before, mkt)["status"] == "not_met"


def read(conn, code: str) -> dict:
    ensure(conn)
    mkt = market(conn, code)
    rows = _rows(conn, code, mkt=mkt)
    name = _name(conn, code)
    price = _price(conn, code, rows, mkt)
    conds = []
    for c in conditions(conn, code):
        ev = evaluate(c, price["price"], rows, mkt)
        conds.append(c | ev | {"newly_met": newly_met(c, ev, price, rows, mkt)})
    return {"code": code, "name": name, "market": mkt, **price, "last_close_date": rows[-1]["trade_date"] if rows else None,
            "chart": _chart(rows) if rows else {"series": []}, "technicals": _technicals(conn, code, rows, mkt) if rows else {},
            "flows": _flows(conn, code) if mkt == "kr" else None, "issues": _issues(conn, code, name, mkt), "conditions": conds}


def status(conn) -> dict:
    """추적 종목 전체의 조건 충족 요약(ia-redesign §4.4, D-301) — read()의 조건 판정만 떼어 낸 가벼운 판. 저장된 시세(국내 stock_prices·장중
    portfolio_quotes, 미국 us_prices)와 조건만 읽는다. 기술적 신호·수급·이슈·차트는 계산하지 않는다(카드 6~7개 대기 10초+ 해소)."""
    ensure(conn)
    items = []
    for code in tracked_codes(conn):
        mkt = market(conn, code)
        rows = _rows(conn, code, n=260, mkt=mkt)
        price = _price(conn, code, rows, mkt)
        conds = []
        for c in conditions(conn, code):
            ev = evaluate(c, price["price"], rows, mkt)
            conds.append({"id": c["id"], "role": c["role"], "label": c["label"], "status": ev["status"],
                          "newly_met": newly_met(c, ev, price, rows, mkt)})
        items.append({"code": code, "name": _name(conn, code), "market": mkt, "as_of": price["as_of"], "conditions": conds,
                      "met": sum(c["status"] == "met" for c in conds), "newly_met": sum(c["newly_met"] for c in conds)})
    return {"items": items, "met": sum(i["met"] for i in items), "newly_met": sum(i["newly_met"] for i in items)}


# ── 알림 ─────────────────────────────────────────────────────────────────────

def _items(conn, mode: str, today: str, live: bool) -> list[tuple[str, str]]:
    """국내: 장중 = 실시간 시세의 급등락·가격 조건, 마감 = 이평선 조건.
    미국: 국내 장중에는 미국장이 닫혀 있어 장 마감 점검에서만 마지막 미국 종가로 가격·이평선 조건을 함께 판정한다(키 = 미국 거래일)."""
    from pipeline.portfolio_alerts import _bucket, _pct
    out = []
    for code in tracked_codes(conn):
        mkt = market(conn, code)
        if mkt == "us" and mode != "close":
            continue
        rows = _rows(conn, code, mkt=mkt)
        if not rows:
            continue
        name, price = _name(conn, code), _price(conn, code, rows, mkt)
        tag = f"🔭 <b>{html.escape(name)}</b>" + (f" ({html.escape(code)}·미국)" if mkt == "us" else "")
        if mkt == "kr" and mode == "intraday" and live and price["source"] == "live":
            b = _bucket(price["change_pct"], DAY_STEP)
            if b:
                out.append((f"track-day:{today}:{code}:{b}", f"{tag} 추적 · 전일 대비 {_pct(price['change_pct'])} · 현재가 {price['price']:,.0f}"))
        for c in conditions(conn, code):
            if c["kind"] == "manual":
                continue
            if mkt == "kr":
                intraday_kind = c["kind"] in ("price_below", "price_above")
                if (mode == "intraday") != intraday_kind:
                    continue                                # 가격 조건은 장중, 이평선 조건은 장 마감에
                if mode == "intraday" and price["source"] != "live":
                    continue
            ev = evaluate(c, price["price"], rows, mkt)
            if ev["status"] == "met":
                icon = {"exit": "🛑", "entry": "✅"}.get(c["role"], "🔔")
                ref = f" (기준 {money(c['level'], mkt)})" if c["level"] else f" ({c['ma']}일선 {money(ev['ref'], mkt)})" if ev.get("ref") else ""
                day = price["as_of"] if mkt == "us" else today      # 미국은 같은 미국 거래일 봉으로 두 번 보내지 않는다
                when = f" · {price['as_of'][5:]} 종가" if mkt == "us" else ""
                out.append((f"track-cond:{day}:{c['id']}", f"{icon} {tag} 조건 충족 · {html.escape(c['label'])}{ref} · 현재 {money(price['price'], mkt)}{when}"))
    return out


def _refresh_us(codes: list[str]) -> None:
    """미국 일봉 캐시 갱신 — fetch_prices는 20시간 안에 받았으면 건너뛴다(cache 패턴). 실패해도 남은 시세로 판정한다."""
    from pipeline.us_data import fetch_prices
    for code in codes:
        try:
            fetch_prices(code)
        except Exception:  # noqa: BLE001
            pass


def alert(conn, mode: str, send, today: str, now: datetime | None = None, dry_run: bool = False, refresh_us=None) -> int:
    """portfolio_alerts.run이 부른다 — 장중: 시세 갱신·급등락·가격 조건·공시(국내만) / 마감: 이평선 조건·기술적 신호·공시, 미국 종목 조건 판정"""
    from pipeline import portfolio as pf
    from pipeline.portfolio_alerts import _send, new_disclosures, technical_signals
    ensure(conn)
    codes = tracked_codes(conn)
    if not codes:
        return 0
    markets = {c: market(conn, c) for c in codes}
    kr = [c for c in codes if markets[c] == "kr"]
    us = [c for c in codes if markets[c] == "us"]
    live = mode == "intraday" and pf.market_hours(now)
    if live and kr:
        pf.refresh_quotes(conn, set(kr), ttl=60)
    if mode == "close" and us:
        (refresh_us or _refresh_us)(us)
    sent = _send(conn, _items(conn, mode, today, live), "", send, dry_run)
    if mode == "close":
        holdings = [{"code": c, "name": _name(conn, c) + (f" ({c}·미국)" if markets[c] == "us" else ""), "market": markets[c]} for c in codes]
        sent += _send(conn, technical_signals(conn, holdings), "📐 <b>추적 종목 새 기술적 신호</b>", send, dry_run)
    sent += _send(conn, new_disclosures([{"code": c, "name": _name(conn, c)} for c in kr], today), "", send, dry_run)
    return sent

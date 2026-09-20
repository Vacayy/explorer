"""통합 검색 — 옴니바(⌘K)의 단일 검색 API (docs/specs/dock-navigation.md §옴니바, D-189).

국내 종목·미국 종목·인물/테마·종목 묶음·스터디 프로젝트를 그룹별로 돌려준다. 순위는 서버가 정한다:
정확 일치 › 이름 접두 › 코드 접두 › 포함, 동순위는 시가총액 내림차순. 모델 호출은 없다.
"""
import sqlite3

from fastapi import APIRouter, Query

from database import get_connection

router = APIRouter(prefix="/api/spine/search", tags=["spine"])

PAGE_LIMIT = 60


def _safe(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:  # 선택 테이블(묶음·프로젝트 등)이 아직 없는 설치
        return []


def _companies(conn, q: str, limit: int) -> list[dict]:
    like, prefix = f"%{q}%", f"{q}%"
    rows = conn.execute(
        """SELECT corp_code, corp_name, stock_code, market, sector,
                  CASE WHEN corp_name = ? OR stock_code = ? THEN 0
                       WHEN corp_name LIKE ? THEN 1
                       WHEN stock_code LIKE ? THEN 2 ELSE 3 END AS rank
           FROM companies WHERE stock_code IS NOT NULL AND (corp_name LIKE ? OR stock_code LIKE ?)
           ORDER BY rank LIMIT ?""", (q, q, prefix, prefix, like, like, PAGE_LIMIT)).fetchall()
    if not rows:
        return []
    codes = [r["stock_code"] for r in rows]
    holders = ",".join("?" * len(codes))
    latest: dict[str, dict] = {}
    for p in _safe(conn, f"""SELECT stock_code, trade_date, close, market_cap,
                                    ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) rn
                             FROM stock_prices WHERE stock_code IN ({holders})
                               AND trade_date >= date((SELECT MAX(trade_date) FROM stock_prices), '-14 days')""", codes):
        entry = latest.setdefault(p["stock_code"], {})
        if p["rn"] == 1:
            entry.update(close=p["close"], market_cap=p["market_cap"], price_date=p["trade_date"])
        elif p["rn"] == 2:
            entry["previous"] = p["close"]
    groups: dict[str, list[str]] = {}
    for g in _safe(conn, f"""SELECT m.stock_code, g.name FROM stock_group_members m JOIN stock_groups g ON g.id = m.group_id
                              WHERE m.stock_code IN ({holders}) ORDER BY g.id""", codes):
        groups.setdefault(g["stock_code"], []).append(g["name"])
    items = []
    for r in rows:
        price = latest.get(r["stock_code"], {})
        close, previous = price.get("close"), price.get("previous")
        items.append({"stock_code": r["stock_code"], "name": r["corp_name"], "market": r["market"], "sector": r["sector"],
                      "close": close, "change_pct": (close - previous) / previous * 100 if close is not None and previous else None,
                      "market_cap": price.get("market_cap"), "price_date": price.get("price_date"),
                      "in_groups": groups.get(r["stock_code"], []), "rank": r["rank"]})
    items.sort(key=lambda i: (i["rank"], -(i["market_cap"] or 0), i["name"]))
    return items[:limit]


def _us(conn, q: str, limit: int) -> list[dict]:
    upper, like = q.upper(), f"%{q}%"
    seen, items = set(), []
    for r in _safe(conn, """SELECT ticker, company_name, group_label FROM transcript_follow
                            WHERE ticker LIKE ? OR company_name LIKE ? ORDER BY CASE WHEN ticker = ? THEN 0 WHEN ticker LIKE ? THEN 1 ELSE 2 END, ticker""",
                   (f"{upper}%", like, upper, f"{upper}%")):
        seen.add(r["ticker"])
        items.append({"ticker": r["ticker"], "name": r["company_name"] or r["ticker"], "group_label": r["group_label"]})
    for r in _safe(conn, "SELECT ticker FROM us_fundamentals WHERE ticker LIKE ? ORDER BY ticker", (f"{upper}%",)):
        if r["ticker"] not in seen:
            items.append({"ticker": r["ticker"], "name": r["ticker"], "group_label": None})
    return items[:limit]


def _entities(conn, q: str, limit: int) -> list[dict]:
    like, prefix = f"%{q}%", f"{q}%"
    return [dict(r) for r in _safe(conn, """SELECT id, type, name FROM entities
        WHERE status = 'active' AND type IN ('person', 'theme', 'sector') AND name LIKE ?
        ORDER BY CASE WHEN name = ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END, type, name LIMIT ?""", (like, q, prefix, limit))]


def _groups(conn, q: str, codes: list[str], limit: int) -> list[dict]:
    holders = ",".join("?" * len(codes)) if codes else "''"
    rows = _safe(conn, f"""SELECT g.id, g.name, g.kind, (SELECT COUNT(*) FROM stock_group_members m WHERE m.group_id = g.id) member_count
                          FROM stock_groups g WHERE g.name LIKE ?
                             OR g.id IN (SELECT group_id FROM stock_group_members WHERE stock_code IN ({holders}))
                          ORDER BY g.id LIMIT ?""", (f"%{q}%", *codes, limit))
    return [dict(r) for r in rows]


def _projects(conn, q: str, limit: int) -> list[dict]:
    return [dict(r) for r in _safe(conn, "SELECT id, title FROM study_projects WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?", (f"%{q}%", limit))]


@router.get("")
def search(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(20, ge=1, le=50)):
    q = q.strip()
    conn = get_connection()
    try:
        companies = _companies(conn, q, limit)
        top_codes = [c["stock_code"] for c in companies[:5]]
        return {"query": q, "companies": companies, "us": _us(conn, q, 6), "entities": _entities(conn, q, 6),
                "groups": _groups(conn, q, top_codes, 5), "projects": _projects(conn, q, 5)}
    finally:
        conn.close()


@router.get("/today")
def today():
    """옴니바 빈 상태: 종목 묶음의 최신 기준일에 새로 켜진 신호."""
    from pipeline import watch_rules as wr
    conn = get_connection()
    try:
        out = []
        for g in _safe(conn, "SELECT id, name FROM stock_groups ORDER BY id"):
            last = conn.execute("SELECT MAX(as_of) d FROM watch_evaluations WHERE group_id=?", (g["id"],)).fetchone()["d"]
            if not last:
                continue
            names = {r["stock_code"]: r["corp_name"] for r in conn.execute(
                "SELECT c.stock_code, c.corp_name FROM companies c JOIN stock_group_members m ON m.stock_code = c.stock_code WHERE m.group_id=?", (g["id"],))}
            for s in wr.signals(conn, g["id"], days=1):
                if s["as_of"] == last:
                    out.append({**s, "name": names.get(s["stock_code"], s["stock_code"]), "group_id": g["id"], "group_name": g["name"]})
        return {"items": out[:12], "as_of": max((i["as_of"] for i in out), default=None)}
    finally:
        conn.close()

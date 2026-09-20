"""통합 검색 — 옴니바(⌘K)의 단일 검색 API (docs/specs/dock-navigation.md §옴니바, D-189).

국내 종목·미국 종목·인물/테마·종목 묶음·스터디 프로젝트를 그룹별로 돌려준다. 순위는 서버가 정한다:
정확 일치 › 이름 접두 › 코드 접두 › 포함, 동순위는 시가총액 내림차순. 모델 호출은 없다.
"""
import re
import sqlite3
import threading

from fastapi import APIRouter, Query

from database import get_connection

router = APIRouter(prefix="/api/spine/search", tags=["spine"])

PAGE_LIMIT = 60
CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_choseong_cache: dict = {"count": -1, "names": []}
_choseong_lock = threading.Lock()


def choseong(text: str) -> str:
    """한글 음절은 초성으로, 그 외 글자는 그대로(공백 제거). 'ㅅㅅㅈㅈ' 검색용."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(CHOSEONG[code // 588])
        elif not ch.isspace():
            out.append(ch)
    return "".join(out)


def is_choseong_query(q: str) -> bool:
    return bool(q) and all(ch in CHOSEONG for ch in q)


def _choseong_index(conn) -> list[tuple[str, str]]:
    """(초성, 종목코드) 목록. companies 행 수가 바뀌면 다시 만든다(3,975행 ≈ 수 ms)."""
    count = conn.execute("SELECT COUNT(*) FROM companies WHERE stock_code IS NOT NULL").fetchone()[0]
    with _choseong_lock:
        if _choseong_cache["count"] != count:
            rows = conn.execute("SELECT corp_name, stock_code FROM companies WHERE stock_code IS NOT NULL").fetchall()
            _choseong_cache.update(count=count, names=[(choseong(r["corp_name"] or ""), r["stock_code"]) for r in rows])
        return _choseong_cache["names"]


def _safe(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:  # 선택 테이블(묶음·프로젝트 등)이 아직 없는 설치
        return []


def _alias_codes(conn, q: str) -> dict[str, str]:
    """별칭 → 종목코드. entity_keywords(SK그룹→SK 등)와 회사 엔티티의 aliases(=종목코드)를 쓴다."""
    out: dict[str, str] = {}
    for r in _safe(conn, """SELECT k.keyword, e.name, e.aliases FROM entity_keywords k JOIN entities e ON e.id = k.entity_id
                            WHERE e.type = 'company' AND e.status = 'active' AND k.keyword LIKE ? LIMIT 20""", (f"%{q}%",)):
        code = None
        if r["aliases"] and re.fullmatch(r"[0-9A-Z]{6}", str(r["aliases"])):
            code = str(r["aliases"])
        else:
            hit = conn.execute("SELECT stock_code FROM companies WHERE corp_name = ? AND stock_code IS NOT NULL LIMIT 1", (r["name"],)).fetchone()
            code = hit["stock_code"] if hit else None
        if code and code not in out:
            out[code] = r["keyword"]
    return out


def _companies(conn, q: str, limit: int) -> list[dict]:
    like, prefix = f"%{q}%", f"{q}%"
    if is_choseong_query(q):
        index = _choseong_index(conn)
        ranked = [(1 if cho.startswith(q) else 3, code) for cho, code in index if q in cho][:PAGE_LIMIT]
        codes = [code for _, code in ranked]
        rank_of = dict((code, rank) for rank, code in ranked)
        rows = [dict(r, rank=rank_of[r["stock_code"]]) for r in _safe(conn, f"""SELECT corp_code, corp_name, stock_code, market, sector
            FROM companies WHERE stock_code IN ({",".join("?" * len(codes)) or "''"})""", codes)] if codes else []
        aliases: dict[str, str] = {}
    else:
        rows = [dict(r) for r in conn.execute(
            """SELECT corp_code, corp_name, stock_code, market, sector,
                      CASE WHEN corp_name = ? OR stock_code = ? THEN 0
                           WHEN corp_name LIKE ? THEN 1
                           WHEN stock_code LIKE ? THEN 2 ELSE 3 END AS rank
               FROM companies WHERE stock_code IS NOT NULL AND (corp_name LIKE ? OR stock_code LIKE ?)
               ORDER BY rank LIMIT ?""", (q, q, prefix, prefix, like, like, PAGE_LIMIT)).fetchall()]
        aliases = _alias_codes(conn, q)
        present = {r["stock_code"] for r in rows}
        extra = [c for c in aliases if c not in present]
        if extra:
            rows += [dict(r, rank=2) for r in conn.execute(f"""SELECT corp_code, corp_name, stock_code, market, sector FROM companies
                WHERE stock_code IN ({",".join("?" * len(extra))})""", extra).fetchall()]
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
                      "in_groups": groups.get(r["stock_code"], []), "rank": r["rank"], "alias": aliases.get(r["stock_code"])})
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


def _mentions(conn, q: str, limit: int = 8) -> list[dict]:
    """문장 안에 이름이 그대로 들어 있는 기업·인물·테마·섹터. 긴 이름을 먼저, 회사는 종목코드를 붙인다."""
    rows = _safe(conn, """SELECT e.id, e.type, e.name, e.aliases FROM entities e
        WHERE e.status = 'active' AND e.type IN ('company', 'person', 'theme', 'sector') AND length(e.name) >= 2 AND instr(?, e.name) > 0
        ORDER BY length(e.name) DESC, e.type LIMIT ?""", (q, limit * 2))
    out, seen = [], set()
    for r in rows:
        name = r["name"]
        # 더 긴 이름 안에 든 조각(SK하이닉스의 'SK'·'이닉스')과 짧은 일반어 테마·섹터('전자'·'투자')는 뺀다.
        if name in seen or any(name in accepted for accepted in seen) or (r["type"] in ("theme", "sector") and len(name) < 3):
            continue
        seen.add(name)
        item = {"id": r["id"], "type": r["type"], "name": name, "stock_code": None}
        if r["type"] == "company":
            if r["aliases"] and re.fullmatch(r"[0-9A-Z]{6}", str(r["aliases"])):
                item["stock_code"] = str(r["aliases"])
            else:
                hit = conn.execute("SELECT stock_code FROM companies WHERE corp_name = ? AND stock_code IS NOT NULL LIMIT 1", (r["name"],)).fetchone()
                item["stock_code"] = hit["stock_code"] if hit else None
        out.append(item)
        if len(out) >= limit:
            break
    return out


@router.get("")
def search(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(20, ge=1, le=50)):
    q = q.strip()
    conn = get_connection()
    try:
        companies = _companies(conn, q, limit)
        top_codes = [c["stock_code"] for c in companies[:5]]
        sentence = len(q.split()) >= 2 or len(q) >= 10
        return {"query": q, "companies": companies, "us": _us(conn, q, 6), "entities": _entities(conn, q, 6),
                "groups": _groups(conn, q, top_codes, 5), "projects": _projects(conn, q, 5),
                "mentions": _mentions(conn, q) if sentence and not is_choseong_query(q) else [],
                "choseong": is_choseong_query(q)}
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

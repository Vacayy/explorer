"""국내 실적 시즌 1단계 — 잠정실적 공시 → 발표일·주가 반응 (ia-redesign §4.22, docs/specs/earnings-season.md §국내 시즌).

미국 시즌(earnings_chain)과 같은 시즌 단위(call_momentum.season: 10~12월 공시 = 3분기 시즌)로 묶는다. LLM 0, 외부 호출 0.
- 발표 = `disclosures`의 잠정실적 공시(report_nm에 '(잠정)실적', '자회사' 제외, 정정 공시 제외). 회사마다 시즌 첫 공시 하나.
  공시 목록은 launchd `krcompany`(매일 21:30)가 채운다. 전 시장 목록 수집이 시작되기 전 시즌은 일부 기업만 있다 →
  `backfill`(scripts/backfill_kr_season.py)로 그 시즌의 공정공시만 다시 받는다.
- 가격 = `stock_prices`만(KRX 대량 조회 금지). 거래일 = 그날 시세가 MARKET_DAY_MIN 종목 이상 있는 날.
- 첫 반응 = 공시 전 거래일 종가 → 공시 다음 거래일 종가(2일 창, 발표 시각을 몰라 장중·장 마감 후를 가르지 않는다).
  다음 거래일 시세가 아직 없으면 공시일 종가까지를 '당일'(same_day)로 보인다. 5일 = 공시 전 종가 → 공시 후 5거래일 종가, 차지 않았으면 '집계 중'(pending).
- 업종 대비 = 같은 `sector_map.group_name` 종목(자신 제외, 발표 여부 무관)의 같은 창 수익률 중앙값을 뺀 값. 표본 PEER_MIN 미만이면 비운다.
- 컨센서스 상회·하회는 하지 않는다(국내 분기 컨센서스 없음). 매출·영업이익 수치는 2단계(본문 파싱) 전까지 null.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

from database import get_connection

PRELIM_WHERE = ("report_nm LIKE '%(잠정)실적%' AND report_nm NOT LIKE '%자회사%' AND report_nm NOT LIKE '[%'")
MARKET_DAY_MIN = 500      # 이 수 이상 종목의 시세가 있는 날만 거래일로 본다(일부 종목만 받은 날 제외)
PEER_MIN = 5              # 업종 대비를 낼 최소 표본
SWEEP_MIN_CORPS = 100     # 하루 공시 회사 수가 이 이상이면 전 시장 목록 수집이 돈 날로 본다
SEASONS_SHOWN = 8         # 시즌 선택기에 보일 최근 시즌 수(2년)


def kst_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()


def _iso(d: str) -> str:
    """'20261103' → '2026-11-03'(이미 ISO면 그대로)"""
    return d if "-" in d else f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def season_of(day: str) -> dict:
    from pipeline.earnings_chain import season_of as us_season_of
    return us_season_of(_iso(day))


def season_by_key(key: str) -> dict:
    from pipeline.earnings_chain import season_by_key as us_season_by_key
    return us_season_by_key(key)


def prev_key(key: str) -> str:
    y, q = int(key[:4]), int(key[-1])
    return f"{y - 1}Q4" if q == 1 else f"{y}Q{q - 1}"


def deadline(key: str) -> str:
    """정기보고서 제출 마감 — 분기·반기 = 분기 말 + 45일, 사업보고서(4분기) = 90일. 주말이면 다음 월요일(공휴일은 따지지 않는다)."""
    y, q = int(key[:4]), int(key[-1])
    end = date(y, q * 3, 30 if q in (2, 3) else 31)
    d = end + timedelta(days=90 if q == 4 else 45)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def basis_of(report_nm: str) -> str:
    return "연결" if "연결" in report_nm else "별도"


# ---------- 순수 계산 (tests/test_kr_season.py) ----------

def window_days(days: list[str], rcept: str) -> dict:
    """거래일 목록(오름차순)과 공시일 → 창의 날짜. base = 공시 전 거래일, d1 = 공시 다음 거래일, d5 = 공시 후 5번째 거래일,
    same = 공시일이 거래일이면 그날. 아직 오지 않은 날은 None."""
    before = [d for d in days if d < rcept]
    after = [d for d in days if d > rcept]
    return {"base": before[-1] if before else None, "d1": after[0] if after else None,
            "d5": after[4] if len(after) >= 5 else None, "same": rcept if rcept in days else None}


def ret(closes: dict, code: str, a: str | None, b: str | None) -> float | None:
    """a 종가 → b 종가 수익률(%). 어느 쪽이든 없으면 None."""
    if not a or not b:
        return None
    pa, pb = closes.get((code, a)), closes.get((code, b))
    if not pa or pb is None:
        return None
    return (pb / pa - 1) * 100


def relative(r: float | None, peer_returns: list[float], min_n: int = PEER_MIN) -> float | None:
    """업종 대비 = 수익률 − 같은 업종 종목 수익률 중앙값. 표본이 min_n 미만이면 None."""
    if r is None or len(peer_returns) < min_n:
        return None
    return r - median(peer_returns)


def reaction(closes: dict, code: str, w: dict, peers: list[str]) -> dict:
    """한 발표의 첫 반응·5일(절대·업종 대비)과 상태. peers = 같은 업종 종목 코드(자신 제외)."""

    def peer_median_input(a, b):
        return [x for x in (ret(closes, p, a, b) for p in peers) if x is not None]

    base = w["base"]
    if w["d1"]:
        end1, s1 = w["d1"], "final"
    else:
        end1, s1 = w["same"], "same_day"
    r1 = ret(closes, code, base, end1)
    x1 = relative(r1, peer_median_input(base, end1)) if r1 is not None else None
    if w["d5"]:
        r5 = ret(closes, code, base, w["d5"])
        x5 = relative(r5, peer_median_input(base, w["d5"])) if r5 is not None else None
        s5 = "final"
    else:
        r5 = x5 = None
        s5 = "pending"
    return {"r1": r1, "x1": x1, "r1_state": s1 if (r1 is not None or s1 == "same_day") else None,
            "r5": r5, "x5": x5, "r5_state": s5 if (r5 is not None or s5 == "pending") else None}


def group_rows(anns: list[dict]) -> list[dict]:
    """업종별 집계 — 발표 수, 첫 반응 중앙값(절대·업종 대비), 업종보다 오른 곳 비율. 확정된 첫 반응만 센다(당일 값 제외)."""
    by: dict[str, list[dict]] = {}
    for a in anns:
        if a["group"]:
            by.setdefault(a["group"], []).append(a)
    out = []
    for g, xs in by.items():
        fin = [a for a in xs if a["r1_state"] == "final"]
        r1 = [a["r1"] for a in fin if a["r1"] is not None]
        x1 = [a["x1"] for a in fin if a["x1"] is not None]
        up = sum(1 for v in x1 if v > 0)
        out.append({"group": g, "n": len(xs), "median_r1": median(r1) if r1 else None, "median_x1": median(x1) if x1 else None,
                    "up_n": up, "base_n": len(x1), "up_ratio": up / len(x1) * 100 if x1 else None})
    return sorted(out, key=lambda r: (-r["n"], r["group"]))


def kpi(anns: list[dict], prev_n: int, today: date, is_current: bool) -> dict:
    fin = [a["x1"] for a in anns if a["r1_state"] == "final" and a["x1"] is not None]
    up = sum(1 for v in fin if v > 0)
    week = None
    if is_current:
        mon = today - timedelta(days=today.weekday())
        lo, hi = mon.isoformat(), (mon + timedelta(days=6)).isoformat()
        in_week = [a["rcept_dt"] for a in anns if lo <= a["rcept_dt"] <= hi]
        week = {"n": len(in_week), "start": lo, "end": hi, "first": min(in_week) if in_week else None, "last": max(in_week) if in_week else None}
    return {"reported": len(anns), "prev_reported": prev_n, "week": week,
            "outperform_n": up, "outperform_base": len(fin), "outperform_ratio": up / len(fin) * 100 if fin else None,
            "median_x1": median(fin) if fin else None}


# ---------- DB 읽기 ----------

def prelim_rows(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        f"SELECT rcp_no, corp_code, corp_name, report_nm, rcept_dt FROM disclosures WHERE {PRELIM_WHERE} ORDER BY rcept_dt, rcp_no")]


def by_season(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """시즌 키 → 회사 → 시즌 첫 잠정실적 공시"""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if not r["rcept_dt"]:
            continue
        key = season_of(r["rcept_dt"])["key"]
        out.setdefault(key, {}).setdefault(r["corp_code"], r)
    return out


def sweep_from(conn) -> str | None:
    """전 시장 공시 목록 수집이 이어진 첫날 — 최근일부터 거슬러 올라가며 하루 공시 회사 수가 SWEEP_MIN_CORPS 이상인 날이 이어지는 동안.
    그 전 날짜는 대상 기업 이력(보유·관심·시총 상위)만 있다."""
    first = None
    for d, n in conn.execute("SELECT rcept_dt, count(DISTINCT corp_code) FROM disclosures GROUP BY rcept_dt ORDER BY rcept_dt DESC LIMIT 800"):
        if n < SWEEP_MIN_CORPS:
            break
        first = d
    return _iso(first) if first else None


def backfilled(key: str) -> bool:
    from services.cache_service import is_cached
    return is_cached(f"krseason:backfill:{key}")


def market_days(conn, lo: str, hi: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT trade_date FROM stock_prices WHERE trade_date BETWEEN ? AND ? GROUP BY trade_date HAVING count(*) >= ? ORDER BY trade_date",
        (lo, hi, MARKET_DAY_MIN))]


def _company_map(conn) -> tuple[dict, dict]:
    """corp_code → {stock_code, name, group}, group → [stock_code]"""
    comp, members = {}, {}
    for r in conn.execute("SELECT c.corp_code, c.corp_name, c.stock_code, m.group_name FROM companies c "
                          "LEFT JOIN sector_map m ON m.sector_name = c.sector WHERE c.stock_code IS NOT NULL AND c.stock_code != ''"):
        comp[r[0]] = {"name": r[1], "stock_code": r[2], "group": r[3]}
        if r[3]:
            members.setdefault(r[3], []).append(r[2])
    return comp, members


def _closes(conn, dates: set[str]) -> tuple[dict, dict]:
    """(코드, 날짜) → 종가, 코드 → 가장 늦은 날짜의 시총"""
    closes, caps, cap_day = {}, {}, {}
    if not dates:
        return closes, caps
    ds = sorted(dates)
    q = ",".join("?" * len(ds))
    for code, d, close, cap in conn.execute(f"SELECT stock_code, trade_date, close, market_cap FROM stock_prices WHERE trade_date IN ({q})", ds):
        if close:
            closes[(code, d)] = close
        if cap and d >= cap_day.get(code, ""):
            caps[code], cap_day[code] = cap, d
    return closes, caps


def announcements(conn, season_rows: dict[str, dict], comp: dict, members: dict, days: list[str]) -> tuple[list[dict], dict]:
    """시즌 발표마다 반응을 계산한다. 반환: (발표 목록 최신순, 시총 사전)"""
    wins = {corp: window_days(days, _iso(r["rcept_dt"])) for corp, r in season_rows.items()}
    need = {d for w in wins.values() for d in w.values() if d}
    if days:
        need.add(days[-1])
    closes, caps = _closes(conn, need)
    out = []
    for corp, r in season_rows.items():
        c = comp.get(corp)
        code = c["stock_code"] if c else None
        group = c["group"] if c else None
        peers = [p for p in members.get(group, []) if p != code] if group else []
        rx = reaction(closes, code, wins[corp], peers) if code else \
            {"r1": None, "x1": None, "r1_state": None, "r5": None, "x5": None, "r5_state": None}
        out.append({"corp_code": corp, "corp_name": (c["name"] if c else None) or (r["corp_name"] or "").strip(),
                    "stock_code": code, "rcept_dt": _iso(r["rcept_dt"]), "rcp_no": r["rcp_no"], "basis": basis_of(r["report_nm"] or ""),
                    "group": group, "market_cap": caps.get(code) if code else None, "d5_date": wins[corp]["d5"],
                    "figures": None, **rx})
    out.sort(key=lambda a: (a["rcept_dt"], a["market_cap"] or 0), reverse=True)
    return out, caps


def overview(season: str | None = None, today: date | None = None) -> dict:
    """GET /api/spine/transcript/season/kr — 시즌 선택(지난 시즌 포함)·KPI·오늘 바뀐 것·캘린더·발표 목록·업종별 집계·아직 발표 전."""
    today = today or kst_today()
    cur = season_of(today.isoformat())["key"]
    key = season or cur
    s = season_by_key(key)
    conn = get_connection()
    try:
        seasons = by_season(prelim_rows(conn))
        comp, members = _company_map(conn)
        lo = (date.fromisoformat(s["start"]) - timedelta(days=14)).isoformat()
        hi = (date.fromisoformat(s["end"]) + timedelta(days=14)).isoformat()
        days = market_days(conn, lo, min(hi, today.isoformat()))
        anns, caps = announcements(conn, seasons.get(key, {}), comp, members, days)
        sweep = sweep_from(conn)
        disc_as_of = conn.execute("SELECT max(rcept_dt) FROM disclosures").fetchone()[0]
    finally:
        conn.close()

    is_current = key == cur
    prev = seasons.get(prev_key(key), {})
    done = {a["corp_code"] for a in anns}
    pending = []
    for corp, r in prev.items():
        c = comp.get(corp)
        if corp in done or not c:
            continue
        pending.append({"corp_code": corp, "corp_name": c["name"], "stock_code": c["stock_code"], "group": c["group"],
                        "market_cap": caps.get(c["stock_code"]), "prev_date": _iso(r["rcept_dt"])})
    pending.sort(key=lambda p: -(p["market_cap"] or 0))

    calendar: dict[str, int] = {}
    for a in anns:
        calendar[a["rcept_dt"]] = calendar.get(a["rcept_dt"], 0) + 1

    changes = {"added_date": None, "added": [], "settled_date": None, "settled": []}
    if is_current and anns:
        last = anns[0]["rcept_dt"]
        changes["added_date"] = last
        changes["added"] = [a["corp_name"] for a in sorted((a for a in anns if a["rcept_dt"] == last), key=lambda a: -(a["market_cap"] or 0))]
        if days:
            settled = sorted((a for a in anns if a["d5_date"] == days[-1]), key=lambda a: -(a["market_cap"] or 0))
            changes["settled"] = [a["corp_name"] for a in settled]
            changes["settled_date"] = settled[0]["rcept_dt"] if settled else None

    keys = sorted(set(seasons) | {cur, key})[-SEASONS_SHOWN:]
    if key not in keys:
        keys = [key] + keys

    def partial_of(k: str) -> bool:
        return bool(sweep and season_by_key(k)["start"] < sweep and not backfilled(k))
    return {
        "season": {"key": key, "label": s["label"], "start": s["start"], "is_current": is_current},
        "seasons": [{"key": k, "label": season_by_key(k)["label"], "count": len(seasons.get(k, {})), "is_current": k == cur,
                     "partial": partial_of(k)} for k in keys],
        "deadline": deadline(key),
        "today": today.isoformat(),
        "prices_as_of": days[-1] if days else None,
        "disclosures_as_of": _iso(disc_as_of) if disc_as_of else None,
        "coverage": {"partial": partial_of(key), "full_from": sweep},
        "kpi": kpi(anns, len(prev), today, is_current),
        "changes": changes,
        "calendar": [{"date": d, "total": n} for d, n in sorted(calendar.items())],
        "announcements": [{k: v for k, v in a.items() if k != "d5_date"} for a in anns],
        "groups": group_rows(anns),
        "pending": pending,
    }


# ---------- 지난 시즌 공시 메우기 (수동 1회, scripts/backfill_kr_season.py) ----------

def backfill(conn, client, key: str) -> dict:
    """전 시장 목록 수집 전 시즌의 잠정실적을 메운다 — list.json을 공정공시(I002)·유가/코스닥으로만 좁혀 시즌 구간을 받는다.
    회사 지정 없는 목록은 기간 3개월 제한이라 시즌(3개월) 한 번이면 된다. 다 받은 시즌은 cache_meta에 표시(다시 안 받음)."""
    from pipeline.kr_company_data import DartRequestError, _list_pages, _store_disclosures
    from services.cache_service import set_cache
    s = season_by_key(key)
    bgn = s["start"].replace("-", "")
    end = (date.fromisoformat(s["end"]) - timedelta(days=1)).strftime("%Y%m%d")
    known = {r[0] for r in conn.execute("SELECT corp_code FROM companies WHERE stock_code IS NOT NULL AND stock_code != ''")}
    stats = {"season": key, "swept": 0, "inserted": 0, "failed": 0}
    for cls in ("Y", "K"):
        try:
            for items in _list_pages(client, {"bgn_de": bgn, "end_de": end, "corp_cls": cls, "pblntf_detail_ty": "I002"}):
                stats["swept"] += len(items)
                stats["inserted"] += _store_disclosures(conn, items, known)
        except DartRequestError:
            stats["failed"] += 1
    if not stats["failed"]:
        set_cache(f"krseason:backfill:{key}", 3650 * 86400)
    stats["calls"] = client.calls
    return stats

"""섹터 맵 RS 계산 — 장기(12M)·단기(1M) 상대강도 4사분면 (LLM 0).

'주가 패턴은 시장 심리의 흔적'을 섹터 차원으로: x=장기 RS(구조적 강도),
y=단기 RS(현재 수급), 크기=시총, 색=5일 흐름. 사분면 = 주도/부상/소외/과열경계.
RS = 대분류별 시총가중 수익률의 백분위(0~100). hover 궤적 = 1·2·3주 전 위치.

집계 축: sector_map(KSIC→투자 언어 대분류 18개, LLM 시드).
계산은 요청 시 (15분 인메모리 캐시) — stock_prices 스냅샷 쿼리 기반.
"""
import time
from datetime import date, timedelta

from database import get_connection

# 장기 창 335일(약 11개월): 380일 백필 한도 안에서 '3주 전 시점의 장기 RS'
# (궤적)까지 계산 가능해야 한다 (365일이면 3주 전 기준가가 백필 밖 → 궤적 유실)
LONG_CAL_DAYS = 335
SHORT_CAL_DAYS = 30
FLOW_DAYS = 5
TRAIL_WEEKS = (1, 2, 3)
_TTL = 900
_cache: dict[str, tuple[float, dict]] = {}


def _snapshot(conn, on_or_before: str) -> dict[str, tuple[float, float]]:
    """종목별 (close, market_cap) — 해당 일자 이전 최근 거래일 기준."""
    rows = conn.execute("""
        SELECT sp.stock_code, sp.close, sp.market_cap
        FROM stock_prices sp
        JOIN (SELECT stock_code, max(trade_date) d FROM stock_prices
              WHERE trade_date <= ? AND close IS NOT NULL GROUP BY stock_code) t
          ON t.stock_code = sp.stock_code AND t.d = sp.trade_date""", (on_or_before,)).fetchall()
    return {r["stock_code"]: (r["close"], r["market_cap"] or 0) for r in rows}


def _members(conn) -> dict[str, str]:
    """종목코드 → 대분류."""
    rows = conn.execute("""
        SELECT c.aliases code, sm.group_name g
        FROM entity_relations er
        JOIN entities c ON c.id = er.src_id AND c.type='company' AND c.aliases IS NOT NULL
        JOIN entities s ON s.id = er.dst_id AND s.type='sector'
        JOIN sector_map sm ON sm.sector_name = s.name
        WHERE er.rel_type='MEMBER_OF'""").fetchall()
    return {r["code"]: r["g"] for r in rows}


def _group_returns(cur: dict, base: dict, members: dict, weights: dict[str, float]) -> dict[str, float]:
    """대분류별 시총가중 수익률 (%).

    가중치는 '최신일 시총' 고정 — 백필된 과거 행에는 market_cap이 없고
    (OHLCV만 저장, 실측: 과거일 mcap 보유 11종목), 주식수 변동은 미미하다.
    """
    acc: dict[str, list[float]] = {}
    for code, (px, _) in cur.items():
        g = members.get(code)
        b = base.get(code)
        w = weights.get(code)
        if not g or not b or not b[0] or not px or not w:
            continue
        acc.setdefault(g, []).append(((px - b[0]) / b[0]) * w)
        acc.setdefault(g + "\x00w", []).append(w)
    out = {}
    for g in list(acc):
        if g.endswith("\x00w"):
            continue
        w = sum(acc[g + "\x00w"])
        if w > 0:
            out[g] = sum(acc[g]) / w * 100
    return out


def _percentile(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    if n <= 1:
        return {k: 50.0 for k, _ in ordered}
    return {k: round(i / (n - 1) * 100) for i, (k, _) in enumerate(ordered)}


def _rs_at(conn, members: dict, as_of: str, weights: dict[str, float]) -> dict[str, dict]:
    cur = _snapshot(conn, as_of)
    d = date.fromisoformat(as_of)
    long_r = _group_returns(cur, _snapshot(conn, (d - timedelta(days=LONG_CAL_DAYS)).isoformat()), members, weights)
    short_r = _group_returns(cur, _snapshot(conn, (d - timedelta(days=SHORT_CAL_DAYS)).isoformat()), members, weights)
    rs_l, rs_s = _percentile(long_r), _percentile(short_r)
    return {g: {"rs_long": rs_l.get(g), "rs_short": rs_s.get(g)} for g in long_r}


def compute_sector_map() -> dict:
    hit = _cache.get("map")
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    if not latest:
        conn.close()
        return {"as_of": None, "groups": []}
    members = _members(conn)
    d = date.fromisoformat(latest)
    cur = _snapshot(conn, latest)
    weights = {c: m for c, (_, m) in cur.items() if m}

    now = _rs_at(conn, members, latest, weights)
    flow = _group_returns(cur, _snapshot(conn, (d - timedelta(days=7)).isoformat()),
                          members, weights)  # ~5거래일
    trails = {w: _rs_at(conn, members, (d - timedelta(weeks=w)).isoformat(), weights)
              for w in TRAIL_WEEKS}
    size: dict[str, float] = {}
    count: dict[str, int] = {}
    for code, (_, mcap) in cur.items():
        g = members.get(code)
        if g and mcap:
            size[g] = size.get(g, 0) + mcap
            count[g] = count.get(g, 0) + 1
    conn.close()

    groups = []
    for g, rs in sorted(now.items(), key=lambda kv: -size.get(kv[0], 0)):
        groups.append({
            "name": g, "market_cap": size.get(g, 0), "stocks": count.get(g, 0),
            "rs_long": rs["rs_long"], "rs_short": rs["rs_short"],
            "chg_5d": round(flow.get(g, 0), 1),
            "trail": [{"weeks_ago": w,
                       "rs_long": trails[w].get(g, {}).get("rs_long"),
                       "rs_short": trails[w].get(g, {}).get("rs_short")} for w in TRAIL_WEEKS],
        })
    result = {"as_of": latest, "groups": groups}
    _cache["map"] = (time.time(), result)
    return result


def group_members_rs(group_name: str, limit: int = 40) -> dict:
    """대분류 소속 종목들의 개별 RS (전 종목 대비 백분위) — 드릴다운."""
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    members = _members(conn)
    codes = [c for c, g in members.items() if g == group_name]
    if not codes or not latest:
        conn.close()
        return {"group": group_name, "items": []}
    d = date.fromisoformat(latest)
    cur = _snapshot(conn, latest)
    base_l = _snapshot(conn, (d - timedelta(days=LONG_CAL_DAYS)).isoformat())
    base_s = _snapshot(conn, (d - timedelta(days=SHORT_CAL_DAYS)).isoformat())

    # 전 종목 수익률 → 백분위 (RS는 시장 전체 대비)
    def rets(base):
        out = {}
        for code, (px, _) in cur.items():
            b = base.get(code)
            if b and b[0] and px:
                out[code] = (px - b[0]) / b[0] * 100
        return out
    rl, rs_ = rets(base_l), rets(base_s)
    pl, ps = _percentile(rl), _percentile(rs_)

    names = {r["stock_code"]: r["corp_name"] for r in conn.execute(
        f"SELECT stock_code, corp_name FROM companies WHERE stock_code IN ({','.join('?'*len(codes))})", codes)}
    conn.close()
    items = [{
        "stock_code": c, "corp_name": names.get(c, c),
        "market_cap": cur.get(c, (0, 0))[1],
        "rs_long": pl.get(c), "rs_short": ps.get(c),
        "ret_1m": round(rs_.get(c), 1) if c in rs_ else None,
        "ret_12m": round(rl.get(c), 1) if c in rl else None,
    } for c in codes if c in cur]
    items.sort(key=lambda x: -(x["market_cap"] or 0))
    return {"group": group_name, "as_of": latest, "items": items[:limit]}

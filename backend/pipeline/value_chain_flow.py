"""돈의 흐름과 다음 스포트라이트 — 밸류체인 칸마다 흐름 크기·가속·교차 확인·시장 반응·관심도 (docs/specs/value-chain.md §11, LLM 0).

예측이 아니라 가설이다(D-095 센스메이킹, D-251: 칸 사이 선행 시차는 대부분 유의하지 않았다).
- 흐름 크기: 최근 3개월(분기 칸은 최신 분기, 발행은 최근 4분기 합)의 전년 대비 증가 금액(USD). 대만달러는 고정 환율 32로 환산 — 칸끼리 크기를 견주는 용도
- 흐름 가속: 칸 상태(가속·전환↑ = +1, 둔화·전환↓ = −1)
- 교차 확인: 교차 확인 지표 중 같은 방향(3개월 YoY > 0)인 비율
- 시장 반응: 칸에 붙은 한국 종목 3개월(63거래일) 주가 수익률 평균, 미국 분기 칸은 구성 회사 주가(us_prices에 있을 때)
- 관심도: 칸 한국 종목을 다룬 문서 수, 최근 30일 대 직전 30일
목록:
- 지금 흐름: 증가 금액이 직전 창(3개월·한 분기 전)보다 많이 늘어난 칸 상위(흐름의 가속)
- 스포트라이트 가설: 가속 + 교차 확인 과반 + 시장 반응이 칸 중앙값 이하 + 관심도가 칸 중앙값 이하(아직 조용함) — 반증 조건을 붙인다
- 엇갈림: 가속 + 교차 확인 과반인데 주가가 칸 중앙값 이하이고 관심은 이미 많은 칸(시장이 흐름을 의심하는 곳 — 이유 확인 대상)
- 식는 칸: 둔화인데 관심도·주가가 높은 칸
- 확인 필요: 스포트라이트·엇갈림 조건을 채웠지만 주 관측이 대리 관측(업계 전체 수출)인 칸 중, 붙은 종목의 공시
  (90일 공급계약 증가·180일 신규시설투자)가 과반 같은 방향이 아닌 칸. 수출 통계에는 비상장·외국계·해외 자가 팹향이
  섞여 종목 매출 증거가 아니다(2026-10-18 점검) — 공시가 받쳐 줄 때만 가설로 올린다
가속 판정은 칸 자기 이력 대비(value_chain.relative_state, ±1σ)다.
"""
from __future__ import annotations

import statistics

TWD_USD = 32.0
STATE_SCORE = {"가속": 1, "전환↑": 1, "유지": 0, "둔화": -1, "전환↓": -1}


def _tw_increment(conn, codes: list[str], back: int = 0) -> tuple[float | None, str | None]:
    """대만 칸 최근 3개월 매출 − 전년 같은 3개월(천 TWD → USD). back=1이면 그 직전 3개월"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue WHERE code IN ({ph}) "
                        f"GROUP BY ym ORDER BY ym DESC LIMIT 3 OFFSET {3 * back}", codes).fetchall()
    if len(rows) < 3 or any(r["n"] != len(codes) or r["ly"] is None for r in rows):
        return None, None
    return sum(r["r"] - r["ly"] for r in rows) * 1000 / TWD_USD, rows[0]["ym"]


def _us_increment(conn, use_key: str, back: int = 0) -> tuple[float | None, str | None]:
    """미국 분기 칸 최신 분기 − 전년 같은 분기(둘 다 있는 회사만). back=1이면 그 직전 분기"""
    rows = conn.execute("SELECT ticker, q, value FROM us_quarterly WHERE use_key=?", (use_key,)).fetchall()
    by: dict[str, dict[str, float]] = {}
    for r in rows:
        by.setdefault(r["q"], {})[r["ticker"]] = r["value"]
    from pipeline.us_fundamentals import TTM
    if use_key in TTM:                    # 발행처럼 들쭉날쭉한 지표는 최근 4분기 합 − 전년 4분기 합(미보고 분기는 수집 때 0으로 채워짐)
        qs = sorted(by)[:len(by) - back]
        if len(qs) < 8:
            return None, None
        tot = lambda win: sum(sum(by[q].values()) for q in win)  # noqa: E731
        return tot(qs[-4:]) - tot(qs[-8:-4]), qs[-1]
    found = 0
    for q in sorted(by, reverse=True):
        prev = by.get(f"{int(q[:4]) - 1}{q[4:]}", {})
        both = [t for t in by[q] if t in prev]
        if both:
            if found == back:
                return sum(by[q][t] - prev[t] for t in both), q
            found += 1
    return None, None


def _kr_increment(conn, hs_codes: list[str], back: int = 0) -> tuple[float | None, str | None]:
    """한국 수출 최근 3개월 − 전년 같은 3개월(USD, 모든 품목이 있는 달만). back=1이면 그 직전 3개월"""
    ph = ",".join("?" * len(hs_codes))
    agg: dict[str, list[float]] = {}
    for r in conn.execute(f"SELECT period, export_usd FROM trade_stats WHERE hs_code IN ({ph}) AND export_usd IS NOT NULL", hs_codes):
        agg.setdefault(r["period"], []).append(r["export_usd"])
    tot = {p: sum(v) for p, v in agg.items() if len(v) == len(hs_codes)}
    ps = sorted(tot)[:len(tot) - 3 * back][-3:]
    prev = [f"{int(p[:4]) - 1}{p[4:]}" for p in ps]
    if len(ps) < 3 or any(p not in tot for p in prev):
        return None, None
    return sum(tot[p] for p in ps) - sum(tot[p] for p in prev), ps[-1]


def _ext_increment(conn, series: str, back: int = 0) -> tuple[float | None, str | None]:
    """외부 월간 시계열 칸 최근 3개월 − 전년 같은 3개월(USD). 단위: USD thousand ×1000, JPY thousand ×1000/150, USD 그대로"""
    rows = conn.execute("SELECT period, value, unit FROM ext_series WHERE series=? ORDER BY period", (series,)).fetchall()
    if not rows:
        return None, None
    fx = {"USD": 1.0, "USD thousand": 1000.0, "JPY thousand": 1000.0 / 150}.get(rows[-1]["unit"])
    if fx is None:
        return None, None
    tot = {r["period"]: r["value"] for r in rows}
    ps = sorted(tot)[:len(tot) - 3 * back][-3:]
    prev = [f"{int(p[:4]) - 1}{p[4:]}" for p in ps]
    if len(ps) < 3 or any(p not in tot for p in prev):
        return None, None
    return (sum(tot[p] for p in ps) - sum(tot[p] for p in prev)) * fx, ps[-1]


def _level(conn, key: str) -> float | None:
    """칸 규모(USD) — 최근 3개월 매출·수출액, 분기 칸은 최신 분기, 회사채(TTM)는 최근 4분기 합. 잔액(RPO)은 흐름이 아니라 None (§14)"""
    from pipeline.us_fundamentals import TTM
    from pipeline.value_chain import EXT_OBS, KR_OBS, NODE_BY_KEY, US_OBS
    if key in US_OBS:
        use = US_OBS[key][0]
        if use == "frontier":
            return None
        # 회사별 가장 최근 분기(회사채는 최근 4분기)의 합 — 같은 분기로 맞추면 먼저 발표한 회사만 남아 규모가 작게 잡힌다
        per: dict[str, list[float]] = {}
        for r in conn.execute("SELECT ticker, value FROM us_quarterly WHERE use_key=? ORDER BY q", (use,)):
            per.setdefault(r["ticker"], []).append(r["value"] or 0.0)
        return sum(sum(v[-4:]) if use in TTM else v[-1] for v in per.values()) if per else None
    if key in KR_OBS:
        hs = KR_OBS[key][0]
        rows = conn.execute(f"SELECT period, SUM(export_usd) v, COUNT(*) n FROM trade_stats WHERE hs_code IN ({','.join('?' * len(hs))}) "
                            "AND export_usd IS NOT NULL GROUP BY period ORDER BY period DESC LIMIT 3", hs).fetchall()
        return sum(r["v"] for r in rows) if len(rows) == 3 and all(r["n"] == len(hs) for r in rows) else None
    if key in EXT_OBS:
        rows = conn.execute("SELECT value, unit FROM ext_series WHERE series=? ORDER BY period DESC LIMIT 3", (EXT_OBS[key][0],)).fetchall()
        fx = {"USD": 1.0, "USD thousand": 1000.0, "JPY thousand": 1000.0 / 150}.get(rows[0]["unit"]) if rows else None
        return sum(r["value"] for r in rows) * fx if len(rows) == 3 and fx else None
    tw = NODE_BY_KEY[key][2] if key in NODE_BY_KEY else []
    if not tw:
        return None
    rows = conn.execute(f"SELECT SUM(revenue) r, COUNT(*) n FROM tw_monthly_revenue WHERE code IN ({','.join('?' * len(tw))}) "
                        "GROUP BY ym ORDER BY ym DESC LIMIT 3", tw).fetchall()
    return sum(r["r"] for r in rows) * 1000 / TWD_USD if len(rows) == 3 and all(r["n"] == len(tw) for r in rows) else None


def edge_flows(edges, level: dict[str, float | None], increment: dict[str, float | None]) -> list[dict]:
    """선별 추정 증가액 — 공급 칸 증가액을 그 칸이 파는 칸들에 사는 칸 규모 비례로 나눈다(실제 거래액 아님, §14).
    규모를 모르는 사는 칸은 사는 칸 규모 중앙값으로 둔다. 공급 칸 증가액을 모르면 flow_usd None"""
    known = [v for v in level.values() if v]
    med = statistics.median(known) if known else 1.0
    buyers: dict[str, list[str]] = {}
    for a, b, *_ in edges:
        buyers.setdefault(a, []).append(b)
    out = []
    for a, b, *_ in edges:
        inc = increment.get(a)
        w = {x: level.get(x) or med for x in buyers[a]}
        flow = inc * w[b] / sum(w.values()) if inc is not None else None
        out.append({"from": a, "to": b, "flow_usd": flow, "basis": "estimate",
                    "buyer_level_imputed": not level.get(b)})
    return out


def _kr_return(conn, codes: list[str]) -> float | None:
    """한국 종목 63거래일 수익률 평균(%)"""
    rets = []
    for c in codes:
        px = [r[0] for r in conn.execute("SELECT close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL "
                                         "ORDER BY trade_date DESC LIMIT 64", (c,))]
        if len(px) == 64 and px[-1]:
            rets.append((px[0] / px[-1] - 1) * 100)
    return round(statistics.mean(rets), 1) if rets else None


def _attention(conn, codes: list[str]) -> tuple[int, int]:
    """칸 한국 종목을 다룬 문서 수(최근 30일, 직전 30일)"""
    if not codes:
        return 0, 0
    ph = ",".join("?" * len(codes))
    q = (f"SELECT COUNT(DISTINCT el.doc_id) FROM entity_links el JOIN entities e ON e.id=el.entity_id "
         f"JOIN raw_documents d ON d.id=el.doc_id WHERE el.link_type='stock' AND e.aliases IN ({ph}) "
         f"AND d.published_at >= datetime('now', ?) AND d.published_at < datetime('now', ?)")
    return (conn.execute(q, (*codes, "-30 days", "+1 day")).fetchone()[0],
            conn.execute(q, (*codes, "-60 days", "-30 days")).fetchone()[0])


def _disclosure(conn, codes: list[str]) -> tuple[int, int]:
    """붙은 종목 중 공시 방향이 up인 수(90일 공급계약 증가 또는 180일 신규시설투자), 전체 수"""
    from pipeline.kr_confirm import disclosure_signal
    return sum(1 for c in codes if disclosure_signal(conn, c)["direction"] == "up"), len(codes)


def compute(vmap: dict | None = None) -> dict:
    from database import get_connection
    from pipeline.value_chain import DEMANDS, EDGES, EXT_OBS, KR_OBS, NODES, US_OBS, obs_kind, read_map
    vmap = vmap or read_map()
    nodes = {n["key"]: n for n in vmap["nodes"]}
    conn = get_connection()
    rows = []
    try:
        for key, name, tw, kr, _ in NODES:
            n = nodes.get(key, {})
            if key in US_OBS:
                fn, arg = _us_increment, US_OBS[key][0]
                kind = "stock" if US_OBS[key][0] in ("frontier",) else "flow"    # RPO는 흐름이 아니라 잔액
            elif key in KR_OBS:
                fn, arg, kind = _kr_increment, KR_OBS[key][0], "flow"
            elif key in EXT_OBS:
                fn, arg, kind = _ext_increment, EXT_OBS[key][0], "flow"
            elif tw:
                fn, arg, kind = _tw_increment, tw, "flow"
            else:
                fn, arg, kind = None, None, "flow"
            inc, period = fn(conn, arg) if fn else (None, None)
            level = _level(conn, key)
            inc_prev, _ = fn(conn, arg, back=1) if fn else (None, None)     # 직전 창(3개월·한 분기 전)의 증가 금액
            aux = [a for a in n.get("aux", []) if not a.get("missing")]
            agree = (sum(1 for a in aux if (a.get("yoy_3m") or 0) > 0) / len(aux)) if aux else None
            att_now, att_prev = _attention(conn, kr)
            proxy = obs_kind(key) == "proxy"
            disc_up, disc_n = _disclosure(conn, kr) if proxy and kr else (0, 0)
            rows.append({"level_usd": level, "obs_kind": obs_kind(key), "disclosure_up": disc_up if proxy else None, "disclosure_n": disc_n if proxy else None,
                         "key": key, "name": name, "state": n.get("state"), "score": STATE_SCORE.get(n.get("state"), 0),
                         "yoy": n.get("yoy_3m"), "increment_usd": inc, "period": period, "kind": kind, "increment_prev_usd": inc_prev,
                         "increment_change_usd": inc - inc_prev if inc is not None and inc_prev is not None else None,
                         "cross_agree": round(agree, 2) if agree is not None else None, "kr": [k["name"] for k in n.get("kr", [])],
                         "kr_return_3m": _kr_return(conn, kr) if kr else None, "attention": att_now, "attention_prev": att_prev})
        demands = []
        for k, name, _ in DEMANDS:                     # 수요 칸도 규모·증가액(사는 칸 규모로 쓰고, 랩·자본으로 파는 공급 칸이기도 하다)
            fn, arg = ((_us_increment, US_OBS[k][0]) if k in US_OBS and US_OBS[k][0] != "frontier" else
                       (_ext_increment, EXT_OBS[k][0]) if k in EXT_OBS else (None, None))
            demands.append({"key": k, "name": name, "level_usd": _level(conn, k), "increment_usd": fn(conn, arg)[0] if fn else None})
    finally:
        conn.close()
    level = {r["key"]: r["level_usd"] for r in rows} | {d["key"]: d["level_usd"] for d in demands}
    increment = {r["key"]: r["increment_usd"] for r in rows if r["kind"] == "flow"} | {d["key"]: d["increment_usd"] for d in demands}
    flows_by_edge = edge_flows(EDGES, level, increment)
    # 지금 흐름: 규모 순은 큰 회사 순일 뿐이라(폭스콘·엔비디아) 증가 금액이 직전 창보다 얼마나 늘었는지(가속)로 고른다
    flows = sorted([r for r in rows if r["kind"] == "flow" and (r["increment_change_usd"] or 0) > 0 and (r["increment_usd"] or 0) > 0],
                   key=lambda r: -r["increment_change_usd"])[:8]
    rets = [r["kr_return_3m"] for r in rows if r["kr_return_3m"] is not None]
    med_ret = statistics.median(rets) if rets else None
    atts = [r["attention"] for r in rows if r["kr"]]
    med_att = statistics.median(atts) if atts else 0
    spotlight, fading, doubted, needs_check = [], [], [], []
    for r in rows:
        if r["kr_return_3m"] is None:
            continue
        unbacked = r["obs_kind"] == "proxy" and r["disclosure_up"] * 2 <= r["disclosure_n"]   # 대리 관측인데 종목 공시가 과반 같은 방향이 아님
        weak_price = med_ret is not None and r["kr_return_3m"] <= med_ret
        quiet = r["attention"] <= med_att
        flowing = r["score"] > 0 and (r["cross_agree"] is None or r["cross_agree"] >= 0.5)
        if flowing and weak_price and unbacked:
            needs_check.append({**r, "why": f"업계 수출 {r['state']}(YoY {r['yoy']}%)인데 종목 3개월 {r['kr_return_3m']}% — 수출 통계는 대리 관측이고 "
                                            f"종목 공시가 받쳐 주지 않음(공급계약·시설투자 증가 {r['disclosure_up']}/{r['disclosure_n']}종목). "
                                            f"분기 실적에서 종목 매출이 같은 방향인지 먼저 확인"})
            continue
        if flowing and weak_price and not quiet:
            doubted.append({**r, "why": f"흐름 {r['state']}(YoY {r['yoy']}%)인데 한국 종목 3개월 {r['kr_return_3m']}% — 문서 {r['attention']}건으로 이미 주목받는 칸. "
                                        f"시장이 흐름의 지속성을 의심하는지(가격 주도·재고·밸류에이션) 확인할 곳"})
        if flowing and weak_price and quiet:
            spotlight.append({**r, "why": f"흐름 {r['state']}(YoY {r['yoy']}%)인데 한국 종목 3개월 수익률 {r['kr_return_3m']}%로 칸 중앙값({round(med_ret, 1)}%) 이하, "
                                          f"문서 {r['attention']}건(직전 {r['attention_prev']}건)",
                              "falsifier": "다음 관측(월매출·수출·분기 실적)에서 상태가 둔화로 꺾이거나 교차 확인 지표가 반대로 돌면 철회"})
        if r["score"] < 0 and (r["attention"] > r["attention_prev"] or (med_ret is not None and r["kr_return_3m"] > med_ret)):
            fading.append({**r, "why": f"흐름 {r['state']}인데 주가·관심은 아직 높음(3개월 {r['kr_return_3m']}%, 문서 {r['attention']}건)"})
    return {"as_of": vmap["as_of"], "twd_usd": TWD_USD, "median_kr_return_3m": med_ret, "median_attention": med_att, "flows": flows,
            "spotlight": sorted(spotlight, key=lambda r: r["kr_return_3m"]), "doubted": doubted, "fading": fading,
            "needs_check": needs_check, "nodes": rows, "demands": demands, "edge_flows": flows_by_edge}

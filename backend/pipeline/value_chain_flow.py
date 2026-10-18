"""돈의 흐름과 다음 스포트라이트 — 밸류체인 칸마다 흐름 크기·가속·교차 확인·시장 반응·관심도 (docs/specs/value-chain.md §11, LLM 0).

예측이 아니라 가설이다(D-095 센스메이킹, D-251: 칸 사이 선행 시차는 대부분 유의하지 않았다).
- 흐름 크기: 최근 3개월(분기 칸은 최신 분기)의 전년 대비 증가 금액(USD). 대만달러는 고정 환율 32로 환산 — 칸끼리 크기를 견주는 용도
- 흐름 가속: 칸 상태(가속·전환↑ = +1, 둔화·전환↓ = −1)
- 교차 확인: 교차 확인 지표 중 같은 방향(3개월 YoY > 0)인 비율
- 시장 반응: 칸에 붙은 한국 종목 3개월(63거래일) 주가 수익률 평균, 미국 분기 칸은 구성 회사 주가(us_prices에 있을 때)
- 관심도: 칸 한국 종목을 다룬 문서 수, 최근 30일 대 직전 30일
목록:
- 지금 흐름: 흐름 크기 상위
- 스포트라이트 가설: 가속 + 교차 확인 과반 + 시장 반응이 칸 중앙값 이하 + 관심도가 칸 중앙값 이하(아직 조용함) — 반증 조건을 붙인다
- 엇갈림: 가속 + 교차 확인 과반인데 주가가 칸 중앙값 이하이고 관심은 이미 많은 칸(시장이 흐름을 의심하는 곳 — 이유 확인 대상)
- 식는 칸: 둔화인데 관심도·주가가 높은 칸
"""
from __future__ import annotations

import statistics

TWD_USD = 32.0
STATE_SCORE = {"가속": 1, "전환↑": 1, "유지": 0, "둔화": -1, "전환↓": -1}


def _tw_increment(conn, codes: list[str]) -> tuple[float | None, str | None]:
    """대만 칸 최근 3개월 매출 − 전년 같은 3개월(천 TWD → USD)"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue WHERE code IN ({ph}) "
                        f"GROUP BY ym ORDER BY ym DESC LIMIT 3", codes).fetchall()
    if len(rows) < 3 or any(r["n"] != len(codes) or r["ly"] is None for r in rows):
        return None, None
    return sum(r["r"] - r["ly"] for r in rows) * 1000 / TWD_USD, rows[0]["ym"]


def _us_increment(conn, use_key: str) -> tuple[float | None, str | None]:
    """미국 분기 칸 최신 분기 − 전년 같은 분기(둘 다 있는 회사만)"""
    rows = conn.execute("SELECT ticker, q, value FROM us_quarterly WHERE use_key=?", (use_key,)).fetchall()
    by: dict[str, dict[str, float]] = {}
    for r in rows:
        by.setdefault(r["q"], {})[r["ticker"]] = r["value"]
    for q in sorted(by, reverse=True):
        prev = by.get(f"{int(q[:4]) - 1}{q[4:]}", {})
        both = [t for t in by[q] if t in prev]
        if both:
            return sum(by[q][t] - prev[t] for t in both), q
    return None, None


def _kr_increment(conn, hs_codes: list[str]) -> tuple[float | None, str | None]:
    """한국 수출 최근 3개월 − 전년 같은 3개월(USD, 모든 품목이 있는 달만)"""
    ph = ",".join("?" * len(hs_codes))
    agg: dict[str, list[float]] = {}
    for r in conn.execute(f"SELECT period, export_usd FROM trade_stats WHERE hs_code IN ({ph}) AND export_usd IS NOT NULL", hs_codes):
        agg.setdefault(r["period"], []).append(r["export_usd"])
    tot = {p: sum(v) for p, v in agg.items() if len(v) == len(hs_codes)}
    ps = sorted(tot)[-3:]
    prev = [f"{int(p[:4]) - 1}{p[4:]}" for p in ps]
    if len(ps) < 3 or any(p not in tot for p in prev):
        return None, None
    return sum(tot[p] for p in ps) - sum(tot[p] for p in prev), ps[-1]


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


def compute(vmap: dict | None = None) -> dict:
    from database import get_connection
    from pipeline.value_chain import KR_OBS, NODES, US_OBS, read_map
    vmap = vmap or read_map()
    nodes = {n["key"]: n for n in vmap["nodes"]}
    conn = get_connection()
    rows = []
    try:
        for key, name, tw, kr, _ in NODES:
            n = nodes.get(key, {})
            if key in US_OBS:
                inc, period = _us_increment(conn, US_OBS[key][0])
                kind = "stock" if US_OBS[key][0] in ("frontier",) else "flow"    # RPO는 흐름이 아니라 잔액
            elif key in KR_OBS:
                inc, period = _kr_increment(conn, KR_OBS[key][0])
                kind = "flow"
            elif tw:
                inc, period = _tw_increment(conn, tw)
                kind = "flow"
            else:
                inc, period, kind = None, None, "flow"
            aux = [a for a in n.get("aux", []) if not a.get("missing")]
            agree = (sum(1 for a in aux if (a.get("yoy_3m") or 0) > 0) / len(aux)) if aux else None
            att_now, att_prev = _attention(conn, kr)
            rows.append({"key": key, "name": name, "state": n.get("state"), "score": STATE_SCORE.get(n.get("state"), 0),
                         "yoy": n.get("yoy_3m"), "increment_usd": inc, "period": period, "kind": kind,
                         "cross_agree": round(agree, 2) if agree is not None else None, "kr": [k["name"] for k in n.get("kr", [])],
                         "kr_return_3m": _kr_return(conn, kr) if kr else None, "attention": att_now, "attention_prev": att_prev})
    finally:
        conn.close()
    flows = sorted([r for r in rows if r["kind"] == "flow" and (r["increment_usd"] or 0) > 0], key=lambda r: -r["increment_usd"])[:8]
    rets = [r["kr_return_3m"] for r in rows if r["kr_return_3m"] is not None]
    med_ret = statistics.median(rets) if rets else None
    atts = [r["attention"] for r in rows if r["kr"]]
    med_att = statistics.median(atts) if atts else 0
    spotlight, fading, doubted = [], [], []
    for r in rows:
        if r["kr_return_3m"] is None:
            continue
        weak_price = med_ret is not None and r["kr_return_3m"] <= med_ret
        quiet = r["attention"] <= med_att
        flowing = r["score"] > 0 and (r["cross_agree"] is None or r["cross_agree"] >= 0.5)
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
            "spotlight": sorted(spotlight, key=lambda r: r["kr_return_3m"]), "doubted": doubted, "fading": fading, "nodes": rows}

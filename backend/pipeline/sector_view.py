"""산업 › 섹터 지도 · 섹터 화면 읽기 (ia-redesign §4.35, D-327) — 저장분만 읽는다. 모델·외부 호출 없음.

- 대표지수: `sector_benchmarks` 대응 ETF의 종가(`sector_benchmark_prices`), 없으면 계산 지수(`sector_index`).
  1일·1개월(21거래일)·3개월(63거래일)은 이 대표지수 기준이다. 코스피는 같은 표의 `^KS11`.
- 상대강도(RS)는 산업 맵 계산(`sector_rs.compute_sector_map`, 섹터 종목 시총 가중)을 그대로 쓴다.
- Peer 그룹: 대응표(`sector_peers`, seed + 자동 제안)의 그룹과 그 아래 제품 그룹(PARENTS 위계, 프론트 lib/peerPresets와 같음).
  중앙값 = 그룹 종목의 n거래일 경로(시작=100) 날짜별 중앙값(프론트 lib/sectorPeers.groupMedianPath와 같음).
- 내러티브 연결(`sector_narratives`·`topic_sectors`): 살아 있는 내러티브의 topic을 섹터 고유 키워드(대분류 이름 조각 ·
  sector_map 업종 이름)로 먼저, 못 잇으면 밸류체인 테마로 잇는다. 같으면 그 섹터, 아니면 topic이 품은 키워드 중 가장 앞의 것.
  일반어(market_today_links.GENERIC_TAGS)는 쓰지 않는다. 연결이 없으면 화면은 '연결된 내러티브 없음'.
- 주요 자료: 최근 10일 블로그·스크랩·웹·유튜브 중 섹터 업종·주제 엔티티(2점)가 붙었거나 섹터 시총 상위 종목(1점)이 셋 이상 붙은 것.
  제목에 섹터 키워드가 든 자료를 먼저, 그 안에서 최신순.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from datetime import date, timedelta

from pipeline.sector_benchmarks import KOSPI, benchmarks

R1M, R3M = 21, 63
CARD_DAYS = 60
DOC_DAYS = 10
DOC_TYPES = ("blog", "scrap", "web", "youtube")
DOC_LIMIT = 30
TOP_STOCKS_FOR_DOCS = 15
_TTL = 900
_cache: dict[str, tuple[float, dict]] = {}

# 리뷰한 상위 그룹 위계 — frontend/src/lib/peerPresets.ts parents와 같게 유지한다
PARENTS = ["power_infrastructure", "semiconductor_value_chain", "defense_value_chain",
           "shipbuilding", "nuclear_value_chain", "battery_value_chain", "beauty_value_chain"]

# 섹터 → 수출입 품목 묶음(trade_follow.group_label) · 대만 공급망 계층(tw_universe.LAYERS) · 미국 실적 시즌 섹터 · 회사채 묶음
TRADE_GROUPS = {
    "반도체·전자부품": ["반도체", "전자부품", "디스플레이", "IT"], "자동차·모빌리티": ["자동차"],
    "전력·에너지": ["전력·에너지", "에너지"], "화학·소재": ["화학·소재", "소재"], "기계·장비": ["기계·장비", "기계"],
    "유통·소비재": ["화장품"], "2차전지·에너지소재": ["2차전지"], "바이오·헬스케어": ["바이오·의료", "의료기기"],
    "항공·방산·우주": ["항공·방산"], "음식료·농수산": ["식품·소비재"], "조선·해운·운송": ["조선·엔진"], "철강·금속": ["철강·금속"],
}
TW_LAYERS = {
    "반도체·전자부품": ["foundry", "design", "osat", "equipment", "substrate", "server", "components", "network", "pc", "mobile"],
    "조선·해운·운송": ["shipping"],
}
US_SEASON = {"반도체·전자부품": ["semis", "semicap"], "전력·에너지": ["power", "dcinfra"], "IT서비스·SW": ["software", "neocloud"],
             "자동차·모빌리티": ["auto"], "항공·방산·우주": ["space"]}
CREDIT_GROUPS = {"반도체·전자부품": "semis", "전력·에너지": "power"}


# ---------- 공통 ----------

def _cached(key: str, latest: str | None, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL and hit[1].get("_latest") == latest:
        return hit[1]["v"]
    v = fn()
    _cache[key] = (time.time(), {"_latest": latest, "v": v})
    return v


def _ret(values: list[float], n: int) -> float | None:
    if len(values) <= n or not values[-1 - n]:
        return None
    return round((values[-1] / values[-1 - n] - 1) * 100, 2)


def bench_series(conn, sector: str, bench: dict | None) -> list[tuple[str, float]]:
    """대표지수 일별 값 [(날짜, 값)] — ETF 종가, 없으면 계산 지수."""
    if bench and bench.get("ticker"):
        q = "SELECT trade_date, close FROM sector_benchmark_prices WHERE ticker = ? ORDER BY trade_date"
        return [(r[0], r[1]) for r in conn.execute(q, (bench["ticker"],))]
    q = "SELECT trade_date, value FROM sector_index WHERE sector = ? ORDER BY trade_date"
    return [(r[0], r[1]) for r in conn.execute(q, (sector,))]


def kospi_series(conn) -> list[tuple[str, float]]:
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT trade_date, close FROM sector_benchmark_prices WHERE ticker = ? ORDER BY trade_date", (KOSPI,))]


def bench_out(bench: dict | None) -> dict:
    b = bench or {}
    return {"kind": "etf" if b.get("ticker") else "computed", "ticker": b.get("ticker"), "name": b.get("name"),
            "tracks": b.get("tracks"), "note": b.get("note")}


def quote(series: list[tuple[str, float]]) -> dict:
    vals = [v for _, v in series]
    return {"last": vals[-1] if vals else None, "last_date": series[-1][0] if series else None,
            "chg_1d": _ret(vals, 1), "ret_1m": _ret(vals, R1M), "ret_3m": _ret(vals, R3M)}


# ---------- Peer 그룹 ----------

def peer_parent(groups: dict[str, dict], members: dict[str, set[str]], gid: str) -> str | None:
    g = groups.get(gid)
    if not g or g["scope"] != "product" or not members.get(gid):
        return None
    return next((p for p in PARENTS if p != gid and groups.get(p, {}).get("scope") == "value_chain"
                 and members[gid] <= members.get(p, set())), None)


def normalized_path(prices: dict, code: str, days: int) -> list[float] | None:
    """프론트 lib/peerPerformance.normalizedPeerPath와 같은 규칙(품질 문제가 있는 종목·빈 값은 뺀다)."""
    dates = prices["dates"]
    if len(dates) < days + 1:
        return None
    start = dates[-days - 1]
    if any(i["code"] == code and start < i["date"] <= prices["asOf"] for i in prices.get("qualityIssues", [])):
        return None
    s = (prices["prices"].get(code) or [])[-days - 1:]
    if len(s) != days + 1 or any(v is None or v <= 0 for v in s):
        return None
    return [v / s[0] * 100 for v in s]


def median_path(prices: dict, codes, days: int) -> list[float] | None:
    paths = [p for c in codes if (p := normalized_path(prices, c, days))]
    if not paths:
        return None
    return [statistics.median(p[i] for p in paths) for i in range(len(paths[0]))]


def _catalog(runtime) -> tuple[dict[str, dict], dict[str, set[str]]]:
    groups = {g.id: {"id": g.id, "name": g.name, "scope": g.scope} for g in runtime.catalog.groups}
    members: dict[str, set[str]] = {}
    for c in runtime.catalog.companies:
        for gid in c.groupIds:
            members.setdefault(gid, set()).add(c.code)
    return groups, members


def sector_group_ids(conn, runtime) -> tuple[dict[str, list[dict]], dict[str, dict], dict[str, set[str]]]:
    """섹터 → [{id, partial, source}] (연결 그룹 다음에 그 아래 제품 그룹, 중복 없이). 카탈로그·구성도 같이 돌려준다."""
    from pipeline.sector_peers import sector_peers as links_of
    groups, members = _catalog(runtime)
    children: dict[str, list[str]] = {}
    for gid in groups:
        p = peer_parent(groups, members, gid)
        if p:
            children.setdefault(p, []).append(gid)
    out: dict[str, list[dict]] = {}
    for entry in links_of(conn, runtime)["sectors"]:
        seen: list[dict] = []
        for link in entry["links"]:
            for gid in [link["group_id"], *children.get(link["group_id"], [])]:
                if gid in groups and all(s["id"] != gid for s in seen):
                    seen.append({"id": gid, "partial": link["partial"], "source": link["source"],
                                 "parent": link["group_id"] if gid != link["group_id"] else None})
        out[entry["sector"]] = seen
    return out, groups, members


def group_rows(runtime, ids: list[dict], groups: dict, members: dict) -> list[dict]:
    prices = runtime.prices.model_dump(mode="json")
    rows = []
    for s in ids:
        codes = members.get(s["id"], set())
        p20, p60 = median_path(prices, codes, 20), median_path(prices, codes, 60)
        rows.append({"id": s["id"], "name": groups[s["id"]]["name"], "scope": groups[s["id"]]["scope"],
                     "parent": s["parent"], "partial": s["partial"], "auto": s["source"] == "auto",
                     "members": len(codes),
                     "med_20d": round(p20[-1] - 100, 2) if p20 else None,
                     "med_60d": round(p60[-1] - 100, 2) if p60 else None})
    return rows


# ---------- 섹터 지도 ----------

def industry_map(conn, runtime=None) -> dict:
    from pipeline.sector_rs import compute_sector_map
    rs = compute_sector_map()
    benches = benchmarks(conn)
    kospi = kospi_series(conn)
    peer_ids: dict[str, list[dict]] = {}
    outside: list[dict] = []
    if runtime is not None:
        peer_ids, groups, members = sector_group_ids(conn, runtime)
        covered = {s["id"] for ids in peer_ids.values() for s in ids}
        outside = [{"id": g["id"], "name": g["name"], "members": len(members.get(g["id"], ()))}
                   for g in groups.values() if g["id"] not in covered and not peer_parent(groups, members, g["id"])]
        outside.sort(key=lambda g: g["name"])
    sectors = []
    for g in rs["groups"]:
        series = bench_series(conn, g["name"], benches.get(g["name"]))
        sectors.append({
            "name": g["name"], "benchmark": bench_out(benches.get(g["name"])), **quote(series),
            "rs_long": g["rs_long"], "rs_short": g["rs_short"], "chg_5d": g["chg_5d"], "trail": g["trail"],
            "market_cap": g["market_cap"], "stocks": g["stocks"],
            "peer_groups": len(peer_ids.get(g["name"], [])) if runtime is not None else None,
            "series": [v for _, v in series[-CARD_DAYS - 1:]],
        })
    return {"as_of": rs["as_of"], "kospi": [v for _, v in kospi[-CARD_DAYS - 1:]], "sectors": sectors,
            "outside_groups": outside, "peers_available": runtime is not None}


# ---------- 내러티브 연결 ----------

def _clean_theme(t: str) -> list[str]:
    """'낸드(NAND)' → ['낸드', 'NAND'], '첨단 패키징(어드밴스드 패키징)' → [...]"""
    out = []
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", t)
    for part in ([m.group(1), m.group(2)] if m else [t]):
        out += [p.strip() for p in part.split("·") if p.strip()]
    return out


def _primary(conn, sector: str) -> set[str]:
    """섹터 고유 키워드 — 대분류 이름 조각 + sector_map 업종 이름(지주·기타는 잡다한 업종이 모여 이름 조각만)."""
    kws = {p for p in sector.split("·") if len(p) >= 2}
    if sector != "지주·기타":      # 예: 지정학 → 지주·기타 같은 대응으로 잇지 않는다
        kws |= {r[0] for r in conn.execute("SELECT sector_name FROM sector_map WHERE group_name = ?", (sector,))}
    from pipeline.market_today_links import GENERIC_TAGS
    return {k for k in kws if k not in GENERIC_TAGS}


def sector_keywords(conn, sector: str) -> set[str]:
    """고유 키워드 + 밸류체인 테마. 테마가 다른 섹터의 고유 키워드면(예: 조선 체인의 '방산') 그 섹터 몫으로 두고 뺀다."""
    from pipeline.market_today_links import GENERIC_TAGS
    kws = _primary(conn, sector)
    others = set().union(*(_primary(conn, g) for (g,) in conn.execute(
        "SELECT DISTINCT group_name FROM sector_map WHERE group_name != ?", (sector,)))) - kws
    for r in conn.execute("SELECT themes_json FROM value_chains WHERE group_name = ?", (sector,)):
        for t in json.loads(r[0] or "[]"):
            kws |= set(_clean_theme(t)) - others
    return {k for k in kws if len(k) >= 2 and k not in GENERIC_TAGS}


def _match(topic: str, keywords: dict[str, set[str]]) -> set[str]:
    exact = {s for s, kws in keywords.items() if topic in kws}
    if exact:
        return exact
    pos = {s: min(topic.find(k) for k in kws if k in topic) for s, kws in keywords.items() if any(k in topic for k in kws)}
    return {s for s, p in pos.items() if p == min(pos.values())} if pos else set()


def topic_sectors(topic: str, primary: dict[str, set[str]], themes: dict[str, set[str]]) -> set[str]:
    """내러티브 topic → 섹터들. 순수 함수(테스트 대상).

    섹터 고유 키워드(이름 조각·업종 이름)를 먼저 본다 — 같으면 그 섹터, 아니면 topic이 품은 키워드 중 가장 앞에 나오는 것의 섹터
    (예: '추론 전환과 메모리 재평가' ∋ '메모리' → 반도체, '반도체 장비' → 반도체). 고유 키워드로 못 잇을 때만 밸류체인 테마로 같은 규칙."""
    return _match(topic, primary) or _match(topic, themes)


def sector_narratives(conn, sector: str) -> list[dict]:
    sectors = [r[0] for r in conn.execute("SELECT DISTINCT group_name FROM sector_map")]
    primary = {s: _primary(conn, s) for s in sectors}
    themes = {s: sector_keywords(conn, s) - primary[s] for s in sectors}
    rows = conn.execute("""SELECT id, topic, title, core_question, doc_count, created_at FROM narratives
        WHERE superseded_at IS NULL ORDER BY created_at DESC""").fetchall()
    return [{"id": r["id"], "topic": r["topic"], "title": r["title"] or r["topic"], "core_question": r["core_question"],
             "docs": r["doc_count"], "updated_at": r["created_at"]} for r in rows if sector in topic_sectors(r["topic"], primary, themes)]


# ---------- 주요 자료 ----------

def sector_docs(conn, sector: str, codes_by_cap: list[str], latest: str) -> list[dict]:
    kws = sector_keywords(conn, sector)
    ph = ",".join("?" * len(kws)) or "''"
    topic_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM entities WHERE type IN ('sector', 'theme') AND name IN ({ph})", sorted(kws))]
    top = codes_by_cap[:TOP_STOCKS_FOR_DOCS]
    ph2 = ",".join("?" * len(top)) or "''"
    stock_ids = [r[0] for r in conn.execute(f"""SELECT e.id FROM entities e JOIN companies c
        ON c.corp_code = json_extract(e.meta_json, '$.corp_code') WHERE e.type = 'company' AND c.stock_code IN ({ph2})""", top)]
    if not topic_ids and not stock_ids:
        return []
    since = (date.fromisoformat(latest) - timedelta(days=DOC_DAYS)).isoformat()
    ids = topic_ids + stock_ids
    ph3 = ",".join("?" * len(ids))
    tp = ",".join("?" * len(DOC_TYPES))
    weight = {i: 2 for i in topic_ids} | {i: 1 for i in stock_ids if i not in topic_ids}
    score: dict[int, int] = {}
    topic_hit: dict[int, bool] = {}
    meta: dict[int, dict] = {}
    for r in conn.execute(f"""SELECT el.doc_id, el.entity_id, d.source_type, d.title, d.published_at FROM entity_links el
            JOIN raw_documents d ON d.id = el.doc_id
            WHERE el.entity_id IN ({ph3}) AND d.published_at >= ? AND d.source_type IN ({tp})""",
                          [*ids, since, *DOC_TYPES]):
        score[r[0]] = score.get(r[0], 0) + weight[r[1]]
        if weight[r[1]] == 2:
            topic_hit[r[0]] = True
        meta[r[0]] = {"id": r[0], "type": r[2], "title": (r[3] or "").strip() or "(제목 없음)", "published_at": r[4]}
    # 업종·주제 태그가 하나 이상(2점) 붙었거나 시총 상위 종목이 셋 이상 붙은 자료만 — 종목 한두 개만 스친 글은 뺀다
    picked = [meta[d] for d, s in score.items() if s >= 2 and (topic_hit.get(d) or s >= 3)]
    # 제목에 섹터 키워드가 든 자료를 먼저, 그 안에서 최신순
    titled = {m["id"] for m in picked if any(k in m["title"] for k in kws)}
    picked.sort(key=lambda m: m["published_at"] or "", reverse=True)
    picked.sort(key=lambda m: m["id"] not in titled)
    return picked[:DOC_LIMIT]


# ---------- 이 산업의 데이터 ----------

def data_links(conn, sector: str, member_caps: dict[str, float]) -> list[dict]:
    out = []
    groups = TRADE_GROUPS.get(sector)
    if groups:
        ph = ",".join("?" * len(groups))
        items = conn.execute(f"SELECT hs_code, item_name, group_label FROM trade_follow WHERE active = 1 AND group_label IN ({ph})",
                             groups).fetchall()
        if items:
            period = conn.execute("SELECT max(period) FROM trade_stats").fetchone()[0]
            best = None
            if period:
                prev = f"{int(period[:4]) - 1}{period[4:]}"
                for it in items:
                    cur = conn.execute("SELECT export_usd FROM trade_stats WHERE hs_code = ? AND period = ?", (it[0], period)).fetchone()
                    old = conn.execute("SELECT export_usd FROM trade_stats WHERE hs_code = ? AND period = ?", (it[0], prev)).fetchone()
                    if cur and cur[0] and (best is None or cur[0] > best["value"]):
                        best = {"name": it[1], "value": cur[0],
                                "yoy": round((cur[0] / old[0] - 1) * 100, 1) if old and old[0] else None}
            out.append({"kind": "trade", "label": "수출입", "title": best["name"] if best else f"품목 {len(items)}",
                        "value": best["value"] if best else None, "value_kind": "usd", "change": best["yoy"] if best else None,
                        "sub": f"{int(period[5:7])}월 · 전년 대비 · 품목 {len(items)}" if best and period else f"품목 {len(items)}",
                        "count": len(items), "href": f"/follow/trade?grp={groups[0]}", "filtered": False})   # grp는 수출입 산업 칩(D-325 개편)이 받는다
    layers = TW_LAYERS.get(sector)
    if layers:
        from pipeline.tw_universe import COMPANIES, LAYERS
        codes = [c for c, _n, layer, *_ in COMPANIES if layer in layers]
        ym = conn.execute("SELECT max(ym) FROM tw_monthly_revenue").fetchone()[0]
        yoys = [r[0] for r in conn.execute(
            f"SELECT yoy_pct FROM tw_monthly_revenue WHERE ym = ? AND yoy_pct IS NOT NULL AND code IN ({','.join('?' * len(codes))})",
            [ym, *codes])] if ym and codes else []
        names = dict(LAYERS)
        title = names[layers[0]] if len(layers) == 1 else f"{names[layers[0]]} 외 {len(layers) - 1}계층"
        out.append({"kind": "taiwan", "label": "대만 공급망", "title": f"{title} {len(codes)}사",
                    "value": round(statistics.median(yoys), 1) if yoys else None, "value_kind": "pct", "change": None,
                    "sub": f"{int(ym[5:7])}월 월매출 전년 대비 중앙값" if ym and yoys else "월매출 대기", "count": len(codes),
                    "href": f"/follow/taiwan?tw_layer={layers[0]}" if len(layers) == 1 else "/follow/taiwan",
                    "filtered": len(layers) == 1})
    from pipeline.value_chain import NODES
    # 이 섹터 종목이 걸린 칸 — 걸린 종목 시총 합이 큰 칸부터(대표 칸 = 링크 대상)
    nodes = sorted(((k, n) for k, n, _tw, kr, _d in NODES if set(kr) & set(member_caps)),
                   key=lambda kn: -sum(member_caps.get(c, 0) for c in next(x[3] for x in NODES if x[0] == kn[0])))
    if nodes:
        out.append({"kind": "valuechain", "label": "밸류체인", "title": nodes[0][1] if len(nodes) == 1 else f"{nodes[0][1]} 외 {len(nodes) - 1}",
                    "value": None, "value_kind": None, "change": None, "sub": f"이 섹터 종목이 걸린 칸 {len(nodes)}",
                    "count": len(nodes), "href": f"/value-chain?node={nodes[0][0]}", "filtered": True})
    keys = US_SEASON.get(sector)
    if keys:
        from pipeline.earnings_chain import SECTORS
        ph = ",".join("?" * len(keys))
        season = conn.execute(f"SELECT max(season) FROM season_themes WHERE sector IN ({ph})", keys).fetchone()[0]
        rows = {r["sector"]: r for r in conn.execute(
            f"SELECT sector, verdict, body_json FROM season_themes WHERE season = ? AND sector IN ({ph}) ORDER BY id", [season, *keys])} if season else {}
        key = next((k for k in keys if k in rows), None)
        if key:
            row = rows[key]
            one = (json.loads(row["body_json"] or "{}") or {}).get("one_line") or ""
            out.append({"kind": "usSeason", "label": "미국 실적 시즌", "title": f"{SECTORS.get(key, (key,))[0]} 섹터 · {season}",
                        "value": None, "value_kind": None, "change": None, "sub": one or "판정 대기",
                        "count": len(rows), "href": f"/follow/transcripts?view=season&sector={key}", "filtered": True,
                        "verdict": row["verdict"]})
    cg = CREDIT_GROUPS.get(sector)
    if cg:
        from pipeline.credit_spreads import COMPANIES as CREDIT, GROUPS
        tickers = [c["ticker"] for c in CREDIT if c["group"] == cg]
        if tickers:
            out.append({"kind": "credit", "label": "회사채", "title": dict(GROUPS)[cg], "value": None, "value_kind": None,
                        "change": None, "sub": f"미국 발행사 {len(tickers)}곳 스프레드", "count": len(tickers),
                        "href": f"/follow/credit?credit={','.join(tickers[:6])}", "filtered": True})
    for d in out:
        d.setdefault("verdict", None)
    return out


# ---------- 섹터 화면 ----------

def _members(conn, sector: str, latest: str) -> list[dict]:
    """구성 종목 — 시총·비중·1일·1개월·RS(전 종목 대비 백분위). sector_rs.group_members_rs 위에 1일만 더한다."""
    from pipeline.sector_rs import _snapshot, group_members_rs
    items = group_members_rs(sector, limit=100000)["items"]
    prev_day = conn.execute("SELECT max(trade_date) FROM stock_prices WHERE trade_date < ?", (latest,)).fetchone()[0]
    cur, prev = _snapshot(conn, latest), _snapshot(conn, prev_day) if prev_day else {}
    total = sum(i["market_cap"] or 0 for i in items) or 1
    out = []
    for i in items:
        c, p = cur.get(i["stock_code"]), prev.get(i["stock_code"])
        out.append({"stock_code": i["stock_code"], "corp_name": i["corp_name"], "market_cap": i["market_cap"],
                    "weight": round((i["market_cap"] or 0) / total * 100, 2),
                    "chg_1d": round((c[0] / p[0] - 1) * 100, 2) if c and p and p[0] else None,
                    "ret_1m": i["ret_1m"], "rs_long": i["rs_long"], "rs_short": i["rs_short"]})
    return out


def _sector_entity(conn, sector: str) -> dict:
    """섹터를 대표하는 업종 엔티티 — 이름 조각 중 type='sector' 엔티티가 있는 첫 것(예: 반도체·전자부품 → 반도체).
    피드 문서 검색 industry 값 · 팔로우 · AI 대화 대상(theme)으로 쓴다."""
    for k in sector.split("·"):
        r = conn.execute("SELECT id, name FROM entities WHERE type = 'sector' AND name = ? AND status = 'active'", (k,)).fetchone()
        if r:
            return {"feed_industry": r["name"], "entity_id": r["id"]}
    return {"feed_industry": None, "entity_id": None}


def overview_row(conn, sector: str) -> dict | None:
    r = conn.execute("SELECT question, bullets_json, narrative_ids, model, generated_at FROM sector_overviews WHERE sector = ?",
                     (sector,)).fetchone()
    if not r:
        return None
    return {"question": r["question"], "bullets": json.loads(r["bullets_json"]), "model": r["model"],
            "generated_at": r["generated_at"], "narrative_ids": [int(x) for x in (r["narrative_ids"] or "").split(",") if x]}


def sector_detail(conn, sector: str, runtime=None) -> dict | None:
    from pipeline.sector_rs import compute_sector_map
    rs = compute_sector_map()
    g = next((x for x in rs["groups"] if x["name"] == sector), None)
    if not g:
        return None
    latest = rs["as_of"]

    def build():
        bench = benchmarks(conn).get(sector)
        series = bench_series(conn, sector, bench)
        kospi = dict(kospi_series(conn))
        members = _members(conn, sector, latest)
        groups_out: list[dict] = []
        if runtime is not None:
            peer_ids, groups, gm = sector_group_ids(conn, runtime)
            groups_out = group_rows(runtime, peer_ids.get(sector, []), groups, gm)
        return {
            "as_of": latest, "name": sector, "benchmark": bench_out(bench), **quote(series),
            "rs_long": g["rs_long"], "rs_short": g["rs_short"], "chg_5d": g["chg_5d"], "trail": g["trail"],
            "market_cap": g["market_cap"], "stocks": g["stocks"],
            "series": [{"d": d, "v": v, "k": kospi.get(d)} for d, v in series],
            "top_weights": members[:8],
            "constituents": members,
            "narratives": sector_narratives(conn, sector),
            "overview": overview_row(conn, sector),
            "docs": sector_docs(conn, sector, [m["stock_code"] for m in members], latest),
            "peer_groups": len(groups_out) if runtime is not None else None,
            "data_links": data_links(conn, sector, {m["stock_code"]: m["market_cap"] or 0 for m in members}),
            **_sector_entity(conn, sector),
        }
    return _cached(f"detail:{sector}:{runtime is not None}", latest, build)


def sector_peer_list(conn, sector: str, runtime) -> dict | None:
    sectors = {r[0] for r in conn.execute("SELECT DISTINCT group_name FROM sector_map")}
    if sector not in sectors:
        return None
    peer_ids, groups, members = sector_group_ids(conn, runtime)
    rows = group_rows(runtime, peer_ids.get(sector, []), groups, members)
    return {"sector": sector, "catalog_as_of": str(runtime.catalog.asOf), "prices_as_of": str(runtime.prices.asOf), "groups": rows}

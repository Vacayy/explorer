"""어젯밤 미국장 브리핑 — 거래대금 상위를 '분위기'로 읽어준다 (docs/specs/us-briefing.md).

결정적 코어(LLM 0): 섹터 클러스터·쏠림 비중 → 개별 이슈 탐지 → 커버 종목 내러티브/언급 enrich.
**그날 시장 담론 주입(D-096)**: 지배 테마 랭킹 + 시장구조 코멘터리 문서(수급·매크로·주도섹터 링크)를 함께 종합에 넣어
거래대금 쏠림(무엇이)을 시장 레벨 촉매(왜·무슨 얘기)와 교차 — 개별 종목 경로로는 못 잡는 시장구조 사건을 잡는다.
LLM 종합(하루 1콜·캐시): 구조화 팩트 + 담론 입력 → 분위기 산문 + 스터디/공유 후보. 촉매 미상은 지어내지 않는다.

리서치를 대신하지 않고 '뭘 스터디하고 뭘 공유할지' 조준하게 하는 게 목적(펀드매니저 피드백, D-095·D-096).
"""
import hashlib
import json
import statistics

from database import get_connection
from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
from pipeline.us_data import resolve_us
from pipeline.us_movers import get_leaders, read_leaders, read_snapshot

# TradingView sector(유한 집합) → KR 라벨. 미매핑은 원문 유지.
_SECTOR_KR = {
    "Electronic Technology": "전자·반도체",
    "Technology Services": "소프트웨어·인터넷",
    "Producer Manufacturing": "산업재·장비",
    "Retail Trade": "리테일",
    "Consumer Durables": "내구소비재",
    "Health Technology": "헬스케어",
    "Energy Minerals": "에너지",
    "Finance": "금융",
    "Communications": "커뮤니케이션",
    "Consumer Services": "소비자서비스",
    "Non-Energy Minerals": "소재",
    "Process Industries": "소재·화학",
    "Transportation": "운송",
    "Utilities": "유틸리티",
    "Commercial Services": "기업서비스",
    "Distribution Services": "유통",
    "Consumer Non-Durables": "필수소비재",
    "Health Services": "헬스서비스",
    "Industrial Services": "산업서비스",
    "Miscellaneous": "기타",
}

_IDIO_CHANGE = 8.0     # |등락률| 이 이상이면 '거래대금+급등락 동반=실이벤트'
# ADR → 담론이 사는 본체(KR) 엔티티명. 비파괴 크로스레퍼런스(하드 병합 대신, D-098):
# ADR 엔티티(SKHY 22건)는 자체 us_prices·ticker 정체성 유지하되, enrich는 본체(SK하이닉스 1349건)를 함께 읽는다.
_ADR_HOME = {"SKHY": "SK하이닉스"}
_MACRO_FLOW = ("수급", "매크로")   # 시장구조 렌즈(담론 문서 선별 시 항상 포함)
_DISCOURSE_THEMES = 12            # 지배 테마 랭킹 상한
_DISCOURSE_DOCS = 8              # 시장구조 코멘터리 문서 상한


def _cluster_label(sector: str | None) -> str:
    if not sector:
        return "기타"
    return _SECTOR_KR.get(sector, sector)


def _home_entity_id(conn, ticker: str) -> int | None:
    """ADR의 본체(KR) 엔티티 id — 비파괴 크로스레퍼런스(_ADR_HOME 이름→id 런타임 해소)."""
    name = _ADR_HOME.get((ticker or "").upper())
    if not name:
        return None
    r = conn.execute("SELECT id FROM entities WHERE type='company' AND name=? LIMIT 1", (name,)).fetchone()
    return r["id"] if r else None


def _enrich_coverage(conn, ticker: str) -> dict:
    """우리 커버리지 — entity(US + ADR 본체) 해소 시 최근 언급수 + 걸린 내러티브. 없으면 uncovered(스터디 후보)."""
    us_eid, _ = resolve_us(conn, ticker)
    home_eid = _home_entity_id(conn, ticker)             # ADR이면 KR 본체도 함께
    ids = [e for e in dict.fromkeys([us_eid, home_eid]) if e]
    if not ids:
        return {"coverage": "uncovered", "entity_id": None, "mentions_3d": 0, "narrative": None}
    ph = ",".join("?" * len(ids))
    m = conn.execute(
        f"SELECT count(DISTINCT el.doc_id) n FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        f"WHERE el.entity_id IN ({ph}) AND rd.published_at >= datetime('now','-3 days')", ids).fetchone()
    nar = conn.execute(
        f"SELECT n.title t FROM entity_relations r JOIN narratives n ON n.id=r.narrative_id "
        f"WHERE (r.src_id IN ({ph}) OR r.dst_id IN ({ph})) AND r.narrative_id IS NOT NULL "
        f"ORDER BY n.id DESC LIMIT 1", ids + ids).fetchone()
    return {"coverage": "covered", "entity_id": us_eid or home_eid,
            "mentions_3d": m["n"] if m else 0, "narrative": nar["t"] if nar else None}


def _build_movers(conn, items: list[dict]) -> list[dict]:
    """스냅샷 행 → 브리핑 mover(클러스터·커버리지 부착)."""
    out = []
    for r in items:
        cov = _enrich_coverage(conn, r["ticker"])
        out.append({
            "rank": r["rank"], "ticker": r["ticker"], "name": r["name"],
            "dollar_volume": r["dollar_volume"], "change_pct": r["change_pct"],
            "sector": r["sector"], "industry": r["industry"], "cluster": _cluster_label(r["sector"]),
            "is_adr": bool(r["is_adr"]), "is_new": bool(r["is_new"]), **cov, "flags": [], "headlines": [],
        })
    return out


def _attach_headlines(conn, movers: list[dict], fetch: bool = True) -> None:
    """개별 이슈 종목의 US 원천 헤드라인 부착 (D-097). fetch=True면 병렬 조회(버튼), False면 캐시 읽기만."""
    from concurrent.futures import ThreadPoolExecutor
    from pipeline.us_news import fetch_news, get_news
    targets = [m["ticker"] for m in movers if m["flags"]]   # 튀는 종목만(비용 바운드)
    if not targets:
        return
    if fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(fetch_news, targets))              # 캐시 미스만 실제 조회
    for m in movers:
        if m["flags"]:
            m["headlines"] = get_news(conn, m["ticker"])


def _read_synthesis(conn, trade_date: str | None) -> dict | None:
    """저장된 종합 순수 읽기 — LLM 없음(일반 로드용). 없으면 None(스켈레톤만)."""
    if not trade_date:
        return None
    row = conn.execute(
        "SELECT synthesis_json FROM us_briefings WHERE trade_date=?", (trade_date,)).fetchone()
    if not row:
        return None
    try:
        return _normalize_synthesis(json.loads(row["synthesis_json"]))
    except Exception:
        return None


def _clusters(movers: list[dict]) -> list[dict]:
    total = sum(m["dollar_volume"] or 0 for m in movers) or 1
    groups: dict[str, list] = {}
    for m in movers:
        groups.setdefault(m["cluster"], []).append(m)
    out = []
    for label, ms in groups.items():
        dv = sum(m["dollar_volume"] or 0 for m in ms)
        changes = [m["change_pct"] for m in ms if m["change_pct"] is not None]
        out.append({
            "label": label, "n": len(ms), "dollar_volume": dv,
            "share_pct": round(dv / total * 100, 1),
            "median_change": round(statistics.median(changes), 1) if changes else 0.0,
            "has_new": any(m["is_new"] for m in ms),
            "tickers": [m["ticker"] for m in ms],
        })
    return sorted(out, key=lambda c: c["dollar_volume"], reverse=True)


def _flag_idiosyncratic(movers: list[dict], clusters: list[dict]) -> None:
    """개별 이슈 탐지 — 급등락·그룹 역행·신규 진입. movers[].flags 를 채운다(in-place)."""
    med = {c["label"]: c["median_change"] for c in clusters}
    size = {c["label"]: c["n"] for c in clusters}
    for m in movers:
        ch = m["change_pct"]
        if ch is not None and abs(ch) >= _IDIO_CHANGE:
            m["flags"].append(f"{'급등' if ch > 0 else '급락'} {ch:+.1f}%")
        if ch is not None and size.get(m["cluster"], 0) >= 3:
            cm = med.get(m["cluster"], 0)
            if cm != 0 and (ch > 0) != (cm > 0):
                m["flags"].append("그룹 역행")
        if m["is_new"]:
            m["flags"].append("신규 진입")


def _gather_discourse(conn, trade_date: str) -> dict:
    """그날 시장 담론 — 지배 테마 랭킹 + 시장구조 코멘터리 문서. LLM 0.

    문서 선별: 매크로/수급 + 그날 주도 섹터 링크 문서를, 다중테마 우선·최신순(시장구조 포스트가 상단).
    개별 종목 경로(ticker→entity)로는 안 닿는 시장 레벨 사건(예: 디레버리징)을 종합에 공급한다.
    """
    day = (trade_date or "")[:10]
    if not day:
        return {"themes": [], "docs": []}
    themes = [{"name": r["name"], "count": r["c"]} for r in conn.execute(
        "SELECT e.name, count(DISTINCT rd.id) c FROM entity_links el "
        "JOIN raw_documents rd ON rd.id=el.doc_id JOIN entities e ON e.id=el.entity_id "
        "WHERE substr(rd.published_at,1,10)=? AND e.type IN ('theme','sector') "
        "GROUP BY e.id ORDER BY c DESC LIMIT ?", (day, _DISCOURSE_THEMES)).fetchall()]
    top_sectors = [r["name"] for r in conn.execute(
        "SELECT e.name FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        "JOIN entities e ON e.id=el.entity_id WHERE substr(rd.published_at,1,10)=? AND e.type='sector' "
        "GROUP BY e.id ORDER BY count(DISTINCT rd.id) DESC LIMIT 2", (day,)).fetchall()]
    lens = list(dict.fromkeys(list(_MACRO_FLOW) + top_sectors))   # 매크로/수급 + 주도섹터
    ph = ",".join("?" * len(lens))
    # 최신순 — 장 마감 무렵의 '정리/총평' 포스트(샤프한 시장구조 서사)가 상단에 오도록.
    # (hits 수 정렬은 다중테마 대형 문서[시황 랩·대형 실적]가 샤프한 저브레드스 서사를 덮어 폐기, D-096)
    rows = conn.execute(
        f"SELECT rd.id, rd.source_type, rd.title, rd.published_at, "
        f"       COALESCE(en.summary, substr(rd.markdown,1,220)) ex "
        f"FROM raw_documents rd JOIN entity_links el ON el.doc_id=rd.id "
        f"JOIN entities e ON e.id=el.entity_id LEFT JOIN enrichments en ON en.doc_id=rd.id "
        f"WHERE substr(rd.published_at,1,10)=? AND e.name IN ({ph}) "
        f"GROUP BY rd.id ORDER BY rd.published_at DESC", (day, *lens)).fetchall()
    seen, docs = set(), []
    for r in rows:                                                # 동일 제목(재게시) 중복 제거
        key = (r["title"] or "")[:40]
        if key in seen:
            continue
        seen.add(key)
        docs.append({"id": r["id"], "source_type": r["source_type"], "title": r["title"],
                     "published_at": r["published_at"], "excerpt": (r["ex"] or "")[:220]})
        if len(docs) >= _DISCOURSE_DOCS:
            break
    return {"themes": themes, "docs": docs}


_INDEX_KR = {"index_sp500": "S&P 500", "index_nasdaq": "나스닥", "index_dow": "다우"}
_MACRO_KR = {"macro_us10y": "미 10Y", "macro_dxy": "달러(DXY)", "macro_gold": "금",
             "macro_oil": "WTI", "macro_hyg": "HYG(하이일드)", "macro_btc": "비트코인"}
_FLOW_DAYS = 10        # 섹터 쏠림 시계열 조회 스냅샷 수
_PRIOR_MOODS = 3       # 종합에 넣을 직전 브리핑 수 (흐름의 연속/단절 판정용)


def _pct_change(rows: list) -> float | None:
    """[(date, value)] 최신 2개의 변화율(%). 재료가 모자라면 None."""
    if len(rows) < 2 or not rows[1]["value"]:
        return None
    return round((rows[0]["value"] - rows[1]["value"]) / abs(rows[1]["value"]) * 100, 2)


def _series(conn, indicator: str, limit: int = 2) -> list:
    return conn.execute(
        "SELECT snapshot_date, value FROM market_indicators WHERE indicator=? AND value IS NOT NULL "
        "ORDER BY snapshot_date DESC LIMIT ?", (indicator, limit)).fetchall()


def _index_moves(conn) -> dict:
    """① 지수 등락 — market_indicators의 index_* 최신 2일 (LLM 0, D-112).

    지수 적재는 별도 파이프라인 소관이라 없을 수도 있다 → 없으면 빈 dict로 조용히 생략(섹션 스킵).
    거래대금 스냅샷 날짜와 어긋날 수 있어 as_of를 함께 반출한다(같은 날인 척하지 않는다).
    """
    out = {"as_of": None, "items": []}
    for ind, label in _INDEX_KR.items():
        rows = _series(conn, ind)
        chg = _pct_change(rows)
        if chg is None:
            continue
        out["items"].append({"name": label, "close": round(rows[0]["value"], 2), "change_pct": chg})
        out["as_of"] = max(out["as_of"] or "", rows[0]["snapshot_date"])
    return out


def _macro_context() -> dict:
    """② 시장을 움직인 요인 — D-101 매크로 리더를 **그대로** 재사용 (LLM 0, D-112).

    새로 수집하지도, 델타를 다시 계산하지도 않는다. 직접 계산했을 때 D-101이
    `_change_pct(back=5)`(5관측 전 대비)인 것을 1일 대비로 재현해 **신호등 해설과 숫자가
    어긋났다**(실측: WTI가 해설 +9.93% vs 자체계산 -0.61%). 산출 주체를 하나로 둔다.

    한계: FOMC·CPI 같은 **이벤트 캘린더는 없다**. '지표가 이렇게 움직였다'까지가
    이 재료의 한계이고, 프롬프트도 그 선을 넘지 말게 지시한다.
    """
    try:
        from pipeline.macro import get_macro
        m = get_macro(with_signal=True)
    except Exception as e:  # noqa: BLE001 — 매크로가 없어도 브리핑은 나가야 한다
        print(f"[us_briefing] 매크로 재료 조회 실패: {type(e).__name__}", flush=True)
        return {}
    items = [{"name": i["label"], "value": i["value"], "change_pct": i["change_pct"],
              "group": i.get("group_label")}
             for i in m.get("items", []) if i.get("change_pct") is not None]
    sig = m.get("signal") or {}
    return {"as_of": m.get("as_of"), "items": items, "lookback": "5관측 전 대비",
            # _read_signal은 as_of를 반환하지 않는다 — 애초에 매크로 as_of로 조회한 행이므로 동일
            "signal": {"as_of": m.get("as_of"), "signal": sig.get("signal"),
                       "headline": sig.get("headline")} if sig.get("signal") else None,
            "degraded": m.get("degraded") or []}


def _flow_history(conn, trade_date: str) -> dict:
    """④ 시계열 흐름 — 최근 스냅샷의 섹터 쏠림 추이 + 직전 브리핑들의 판단 (LLM 0, D-112).

    하루치만 보면 '오늘 반도체 61%'가 평소인지 이례인지 알 수 없다. 같은 섹터의 비중이
    며칠에 걸쳐 어떻게 움직였는지, 그리고 내가 직전에 뭐라고 읽었는지를 함께 준다.
    us_movers 보존이 30 스냅샷이라 여기서 실제 추이가 나온다(D-112 전까지는 7이라 불가).
    """
    dates = [r["trade_date"] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM us_movers WHERE trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?", (trade_date, _FLOW_DAYS))]
    sector_share: dict[str, list] = {}
    for d in reversed(dates):                       # 과거 → 최신 순으로 시계열 구성
        rows = conn.execute(
            "SELECT sector, sum(dollar_volume) dv FROM us_movers WHERE trade_date=? GROUP BY sector",
            (d,)).fetchall()
        total = sum(r["dv"] or 0 for r in rows) or 1
        for r in rows:
            label = _cluster_label(r["sector"])
            sector_share.setdefault(label, []).append(
                {"date": d, "share_pct": round((r["dv"] or 0) / total * 100, 1)})

    # 최신 비중 상위 섹터만 (추이가 의미 있는 것)
    ranked = sorted(sector_share.items(),
                    key=lambda kv: kv[1][-1]["share_pct"] if kv[1] else 0, reverse=True)[:4]
    prior = [dict(r) for r in conn.execute(
        "SELECT trade_date, synthesis_json FROM us_briefings WHERE trade_date < ? "
        "ORDER BY trade_date DESC LIMIT ?", (trade_date, _PRIOR_MOODS))]
    moods = []
    for p in prior:
        try:
            j = json.loads(p["synthesis_json"])
        except Exception:
            continue
        text = j.get("issues") or j.get("mood") or ""     # 구 스키마(mood) 호환
        if text:
            moods.append({"trade_date": p["trade_date"], "text": text[:400]})
    return {"dates": dates, "sectors": [{"label": k, "series": v} for k, v in ranked],
            "prior_moods": moods}


def _signature(trade_date: str, movers: list[dict], discourse: dict, extra: dict) -> str:
    basis = trade_date + "|" + "|".join(
        f"{m['ticker']}:{round(m['change_pct'] or 0)}:{m['coverage']}:{int(bool(m['flags']))}"
        for m in movers)
    basis += "|D:" + ",".join(str(d["id"]) for d in discourse.get("docs", []))
    basis += "|H:" + ",".join(h["url"] for m in movers for h in m.get("headlines", []))
    # 맥락 재료는 '날짜'만 넣는다 (D-112) — 값 지터마다 재종합하면 sonnet 비용이 새고,
    # 새 하루치가 들어오면 signature가 바뀌어 정상적으로 다시 쓴다.
    basis += "|I:" + (extra.get("index_as_of") or "")
    basis += "|M:" + ",".join(sorted(extra.get("macro_dates") or []))
    basis += "|F:" + ",".join(extra.get("flow_dates") or [])
    return hashlib.sha256(basis.encode()).hexdigest()


def _synthesis_prompt(clusters, idio, movers, discourse, indices, macro, flow, trade_date) -> str:
    """4섹션 브리핑 프롬프트 (D-112) — 하루치 스냅샷에 **맥락 3층**을 얹는다.

    v1은 거래대금 쏠림 + 그날 담론만 봤다. 그러면 '오늘 반도체 61%'가 평소인지 이례인지,
    무엇이 시장 전체를 밀었는지 알 수 없다. 지수(어디서 끝났나)·매크로(무엇이 밀었나)·
    시계열(며칠째 흐름인가)을 함께 넣어 하루를 흐름 위에 놓는다.
    """
    def fmt_c(c):
        return (f"- {c['label']}: {c['n']}종목·거래대금비중 {c['share_pct']}%·대표등락 "
                f"{c['median_change']:+.1f}%{'·신규포함' if c['has_new'] else ''} ({', '.join(c['tickers'])})")

    def fmt_i(m):
        cov = m["narrative"] or ("커버 안 됨" if m["coverage"] == "uncovered" else "내러티브 없음")
        head = ""
        if m.get("headlines"):
            head = "\n    " + "\n    ".join(
                f"· [{h['publisher'] or '?'}] {h['title']}" + (f" — {h['summary'][:100]}" if h.get("summary") else "")
                for h in m["headlines"][:2])
        return (f"- {m['ticker']} ({m['name']}): {', '.join(m['flags'])} · 최근언급 {m['mentions_3d']}건 "
                f"· 관련내러티브: {cov}{head}")

    idx = "- 없음"
    if indices.get("items"):
        same = indices["as_of"] == trade_date
        idx = (f"({indices['as_of']} 종가"
               + ("" if same else f" — 거래대금 기준일 {trade_date}와 다름, 반드시 날짜를 밝힐 것")
               + ")\n" + "\n".join(
                   f"- {i['name']}: {i['close']:,} ({i['change_pct']:+.2f}%)" for i in indices["items"]))

    mac = "- 없음"
    if macro.get("items"):
        mac = (f"({macro.get('as_of')} 기준 · 변화율은 {macro.get('lookback')})\n" + "\n".join(
            f"- {i['name']}: {i['value']:,} ({i['change_pct']:+.2f}%)" for i in macro["items"]))
        if macro.get("signal"):
            mac += (f"\n- 매크로 신호등({macro['signal']['as_of']}): "
                    f"{macro['signal']['signal']} — {macro['signal']['headline']}")
        if macro.get("degraded"):
            mac += f"\n- (수집 실패로 빠진 지표: {', '.join(macro['degraded'])})"

    fl = "- 없음"
    if flow.get("sectors"):
        fl = "\n".join(
            "- {}: {}".format(s["label"], " → ".join(
                f"{x['date'][5:]} {x['share_pct']}%" for x in s["series"]))
            for s in flow["sectors"])
        if flow.get("prior_moods"):
            fl += "\n\n[직전 브리핑에서 내가 읽은 것]\n" + "\n".join(
                f"- {m['trade_date']}: {m['text']}" for m in flow["prior_moods"])

    themes = ", ".join(f"{t['name']}({t['count']})" for t in discourse.get("themes", [])) or "없음"
    docs = "\n".join(
        f"- [{d['source_type']}] {d['title']}: {(d['excerpt'] or '').strip()[:180]}"
        for d in discourse.get("docs", [])) or "- 없음"

    return (
        "당신은 미국장 마감 후 아침 브리핑을 쓰는 애널리스트다. 아래 재료로 4개 섹션을 쓴다.\n\n"
        f"[1. 지수 마감]\n{idx}\n\n"
        f"[2. 매크로 지표 — 전일 대비]\n{mac}\n\n"
        f"[3-a. 거래대금 섹터 쏠림]\n" + "\n".join(fmt_c(c) for c in clusters) + "\n\n"
        f"[3-b. 거래대금 개별 이슈 종목]\n" + ("\n".join(fmt_i(m) for m in idio) or "- 없음") + "\n\n"
        f"[3-c. 그날 시장 담론 — 지배 테마(문서수)]\n{themes}\n\n"
        f"[3-d. 그날 시장 담론 — 시장구조 코멘터리]\n{docs}\n\n"
        f"[4. 최근 스냅샷의 섹터 거래대금 비중 추이(과거→최신)]\n{fl}\n\n"
        "임무 — 각 항목을 **하나의 문단**으로. 전체 4문단, 문단당 3~5문장:\n"
        "① index_summary: 어제 장이 어디서 어떻게 끝났는지. 지수 등락률을 실제 숫자로 쓰고, "
        "지수는 잠잠한데 개별 거래대금은 쏠렸다면 그 괴리를 짚어라.\n"
        "② drivers: 시장 전체를 움직인 요인. 매크로 지표 변화([2])와 담론([3-c],[3-d])을 교차해 "
        "'무엇이 위험선호를 밀거나 눌렀나'를 말하라. "
        "**규율: 재료에 없는 이벤트를 지어내지 마라.** 여기엔 FOMC·CPI 같은 발표 일정 정보가 없다. "
        "지표가 '어떻게 움직였다'까지만 말하고, 원인을 모르면 모른다고 하라.\n"
        "③ issues: 거래대금이 어디로 쏠렸고 그룹으로 안 풀리는 개별 움직임은 무엇인지. "
        "담론이 특정 사건을 지목하면 이름을 명시하고, 헤드라인이 있으면 그 종목의 촉매로 삼아라. "
        "거래대금 급증의 **성격**(신규 매수 랠리인지, 청산·디레버리징·되돌림인지)을 근거와 함께 판단하라.\n"
        "④ flow: [4]의 비중 추이와 [직전 브리핑에서 내가 읽은 것]을 대조해 "
        "**어제가 흐름의 연속인지 단절인지** 판정하라. 어느 섹터로 자금이 옮겨가는 중인지, "
        "직전 판단이 유지되는지 뒤집혔는지 명시하라. 추이 데이터가 2일 이하면 그렇다고 말하라.\n\n"
        "공통 규율: 근거 있는 것만. 촉매를 모르면 지어내지 말고 스터디 후보로 돌려라.\n"
        "JSON만 출력: {\"index_summary\": \"…\", \"drivers\": \"…\", \"issues\": \"…\", \"flow\": \"…\", "
        "\"study_candidates\": [\"티커 — 왜 스터디해야 하는지 한 줄\"], "
        "\"share_candidates\": [\"티커/주제 — 이미 내러티브 있어 공유할 만한 것 한 줄\"]}"
    )


SYNTH_SECTIONS = ("index_summary", "drivers", "issues", "flow")


def _normalize_synthesis(data: dict) -> dict:
    """저장/반환 형태 통일 + 구 스키마 호환.

    D-112 이전 행은 `mood` 하나뿐이다 — 그 시절 산문은 지금의 issues에 해당하므로
    거기로 흘려보내 과거 브리핑도 그대로 읽히게 한다(히스토리를 깨지 않는다).
    """
    out = {k: (data.get(k) or "") for k in SYNTH_SECTIONS}
    if not out["issues"] and data.get("mood"):
        out["issues"] = data["mood"]
    out["study_candidates"] = data.get("study_candidates") or []
    out["share_candidates"] = data.get("share_candidates") or []
    return out


def _synthesize(conn, trade_date: str, signature: str, clusters, idio, movers,
                discourse, indices, macro, flow) -> dict | None:
    """LLM 종합 — 캐시(signature 불변 재사용). 엔진 미가용이면 None(구조화 스켈레톤만)."""
    cached = conn.execute(
        "SELECT signature, synthesis_json FROM us_briefings WHERE trade_date=?", (trade_date,)).fetchone()
    if cached and cached["signature"] == signature:
        try:
            return _normalize_synthesis(json.loads(cached["synthesis_json"]))
        except Exception:
            pass
    if llm_engine() != "claude-code":
        return None
    try:
        data = _parse_json(_call_claude_code(
            _synthesis_prompt(clusters, idio, movers, discourse, indices, macro, flow, trade_date),
            model="sonnet", timeout=300))
    except Exception as e:  # noqa: BLE001 — 원인을 로그로 남긴다(구 silent-None 대비)
        print(f"[us_briefing] 종합 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return None
    synthesis = _normalize_synthesis(data)
    if not any(synthesis[k] for k in SYNTH_SECTIONS):     # 전 섹션 공백이면 저장 가치 없음
        return None
    conn.execute(
        "INSERT OR REPLACE INTO us_briefings (trade_date, signature, synthesis_json, model, created_at) "
        "VALUES (?,?,?, 'sonnet', datetime('now'))",
        (trade_date, signature, json.dumps(synthesis, ensure_ascii=False)))
    conn.commit()
    return synthesis


def list_briefings(limit: int = 30) -> list[dict]:
    """저장된 브리핑 목록(최신순) — 과거 조회 진입점 (D-112).

    D-112 이전엔 적재만 하고 읽을 길이 없어 사실상 write-only였다.
    """
    conn = get_connection()
    try:
        return [{"trade_date": r["trade_date"], "model": r["model"], "created_at": r["created_at"]}
                for r in conn.execute(
                    "SELECT trade_date, model, created_at FROM us_briefings "
                    "ORDER BY trade_date DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def _staleness(trade_date: str | None) -> int | None:
    """거래대금 스냅샷이 며칠 묵었나 (KST 오늘 기준). 날짜가 없으면 None.

    브리핑은 '어젯밤'을 자처하는데 스냅샷이 며칠 전 것이면 프레임이 거짓이 된다.
    날짜만 정직하게 찍고 마는 대신 경과일을 명시 반출해 화면·텔레그램이 경고할 수 있게 한다.
    """
    if not trade_date:
        return None
    from datetime import datetime, timedelta, timezone
    try:
        d = datetime.strptime(trade_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (datetime.now(timezone(timedelta(hours=9))).date() - d).days)


def build_briefing(force: bool = False, trade_date: str | None = None) -> dict:
    """어젯밤 미국장 브리핑 — 구조화(LLM 0) + 4섹션 종합(하루 1콜·캐시, D-112).

    반환 {status, trade_date, fetched_at, error, stale_days, clusters, idiosyncratic,
          movers, market_themes, market_docs, indices, macro, flow, synthesis|None}.
    LLM 미가용이어도 결정적 스켈레톤은 항상 채워진다.

    trade_date: 과거 브리핑 조회(읽기 전용 — 재수집·재종합 없음, D-112).
    """
    if trade_date:                                          # 과거 조회는 순수 읽기
        return _read_past(trade_date)

    # force(버튼)=재수집+재종합, force=False(일반 로드)=최신 스냅샷 순수 읽기(네트워크·LLM 없음, D-100)
    lead = get_leaders(force=True) if force else read_leaders()
    base = {"status": lead["status"], "trade_date": lead["trade_date"],
            "fetched_at": lead["fetched_at"], "error": lead["error"],
            "stale_days": _staleness(lead["trade_date"]),
            "clusters": [], "idiosyncratic": [], "movers": [], "market_themes": [],
            "market_docs": [], "indices": {}, "macro": {}, "flow": {}, "synthesis": None}
    if not lead["items"]:
        return base

    conn = get_connection()
    try:
        movers = _build_movers(conn, lead["items"])
        clusters = _clusters(movers)
        _flag_idiosyncratic(movers, clusters)
        _attach_headlines(conn, movers, fetch=force)       # 버튼만 새 뉴스 조회, 로드는 캐시 읽기
        idio = [m for m in movers if m["flags"]]
        discourse = _gather_discourse(conn, lead["trade_date"])
        indices = _index_moves(conn)                        # ① 지수 (D-112)
        macro = _macro_context()                            # ② 매크로 (D-112)
        flow = _flow_history(conn, lead["trade_date"])      # ④ 시계열 (D-112)
        if force:                                          # 버튼: 재종합(sonnet, signature 캐시)
            sig = _signature(lead["trade_date"], movers, discourse, {
                "index_as_of": indices.get("as_of"),
                "macro_dates": [macro.get("as_of") or ""],
                "flow_dates": flow.get("dates", []),
            })
            synthesis = _synthesize(conn, lead["trade_date"], sig, clusters, idio, movers,
                                    discourse, indices, macro, flow)
        else:                                              # 로드: 저장된 종합 읽기(LLM 없음)
            synthesis = _read_synthesis(conn, lead["trade_date"])
    finally:
        conn.close()

    base.update({"clusters": clusters, "idiosyncratic": idio, "movers": movers,
                 "market_themes": discourse["themes"], "market_docs": discourse["docs"],
                 "indices": indices, "macro": macro, "flow": flow, "synthesis": synthesis})
    return base


def _read_past(trade_date: str) -> dict:
    """과거 브리핑 — 저장된 종합 + 그날 스냅샷(보존 기간 내라면). LLM·네트워크 0.

    산문은 영구 보존이지만 movers 스냅샷은 RETAIN_DAYS 뒤 사라진다 —
    그 경우 근거 표 없이 산문만 반환하고 status='partial'로 그 사실을 드러낸다.
    """
    conn = get_connection()
    try:
        synthesis = _read_synthesis(conn, trade_date)
        snapshot = read_snapshot(conn, trade_date)
        base = {"status": "ok" if snapshot else ("partial" if synthesis else "error"),
                "trade_date": trade_date, "fetched_at": snapshot[0]["fetched_at"] if snapshot else None,
                "error": None if (snapshot or synthesis) else "해당 날짜의 브리핑이 없습니다",
                "stale_days": _staleness(trade_date),
                "clusters": [], "idiosyncratic": [], "movers": [], "market_themes": [],
                "market_docs": [], "indices": {}, "macro": {}, "flow": {}, "synthesis": synthesis}
        if not snapshot:
            if synthesis:
                base["error"] = "근거 스냅샷은 보존 기간이 지나 삭제됐습니다 (종합만 표시)"
            return base
        movers = _build_movers(conn, snapshot)
        clusters = _clusters(movers)
        _flag_idiosyncratic(movers, clusters)
        _attach_headlines(conn, movers, fetch=False)
        discourse = _gather_discourse(conn, trade_date)
        base.update({"clusters": clusters, "idiosyncratic": [m for m in movers if m["flags"]],
                     "movers": movers, "market_themes": discourse["themes"],
                     "market_docs": discourse["docs"]})
        return base
    finally:
        conn.close()

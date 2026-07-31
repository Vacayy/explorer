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
from pipeline.us_movers import get_leaders

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
_MACRO_FLOW = ("수급", "매크로")   # 시장구조 렌즈(담론 문서 선별 시 항상 포함)
_DISCOURSE_THEMES = 12            # 지배 테마 랭킹 상한
_DISCOURSE_DOCS = 8              # 시장구조 코멘터리 문서 상한


def _cluster_label(sector: str | None) -> str:
    if not sector:
        return "기타"
    return _SECTOR_KR.get(sector, sector)


def _enrich_coverage(conn, ticker: str) -> dict:
    """우리 커버리지 — entity 해소 시 최근 언급수 + 걸린 내러티브. 없으면 uncovered(스터디 후보)."""
    eid, _ = resolve_us(conn, ticker)
    if eid is None:
        return {"coverage": "uncovered", "entity_id": None, "mentions_3d": 0, "narrative": None}
    m = conn.execute(
        "SELECT count(DISTINCT el.doc_id) n FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        "WHERE el.entity_id=? AND rd.published_at >= datetime('now','-3 days')", (eid,)).fetchone()
    nar = conn.execute(
        "SELECT n.title t FROM entity_relations r JOIN narratives n ON n.id=r.narrative_id "
        "WHERE (r.src_id=? OR r.dst_id=?) AND r.narrative_id IS NOT NULL ORDER BY n.id DESC LIMIT 1",
        (eid, eid)).fetchone()
    return {"coverage": "covered", "entity_id": eid,
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


def _attach_headlines(conn, movers: list[dict]) -> None:
    """개별 이슈 종목의 US 원천 헤드라인 병렬 수집·부착 (D-097) — 개별 '왜' 채움. 실패는 빈 리스트."""
    from concurrent.futures import ThreadPoolExecutor
    from pipeline.us_news import fetch_news, get_news
    targets = [m["ticker"] for m in movers if m["flags"]]   # 튀는 종목만(비용 바운드)
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(fetch_news, targets))                  # 캐시 미스만 실제 조회
    for m in movers:
        if m["flags"]:
            m["headlines"] = get_news(conn, m["ticker"])


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


def _signature(trade_date: str, movers: list[dict], discourse: dict) -> str:
    basis = trade_date + "|" + "|".join(
        f"{m['ticker']}:{round(m['change_pct'] or 0)}:{m['coverage']}:{int(bool(m['flags']))}"
        for m in movers)
    basis += "|D:" + ",".join(str(d["id"]) for d in discourse.get("docs", []))
    basis += "|H:" + ",".join(h["url"] for m in movers for h in m.get("headlines", []))
    return hashlib.sha256(basis.encode()).hexdigest()


def _synthesis_prompt(clusters, idio, movers, discourse) -> str:
    def fmt_c(c):
        return f"- {c['label']}: {c['n']}종목·거래대금비중 {c['share_pct']}%·대표등락 {c['median_change']:+.1f}%{'·신규포함' if c['has_new'] else ''} ({', '.join(c['tickers'])})"
    def fmt_i(m):
        cov = m["narrative"] or ("커버 안 됨" if m["coverage"] == "uncovered" else "내러티브 없음")
        head = ""
        if m.get("headlines"):
            head = "\n    " + "\n    ".join(
                f"· [{h['publisher'] or '?'}] {h['title']}" + (f" — {h['summary'][:100]}" if h.get('summary') else "")
                for h in m["headlines"][:2])
        return f"- {m['ticker']} ({m['name']}): {', '.join(m['flags'])} · 최근언급 {m['mentions_3d']}건 · 관련내러티브: {cov}{head}"
    themes = ", ".join(f"{t['name']}({t['count']})" for t in discourse.get("themes", [])) or "없음"
    docs = "\n".join(
        f"- [{d['source_type']}] {d['title']}: {(d['excerpt'] or '').strip()[:180]}"
        for d in discourse.get("docs", [])) or "- 없음"
    return (
        "당신은 미국장 마감 후 아침 브리핑을 쓰는 애널리스트다. 아래는 (1) 전일 미국시장 거래대금 상위 20의 "
        "구조화 팩트와 (2) 같은 날 시장 담론(주로 한국 소스지만 AI·반도체·수급·매크로 같은 테마는 글로벌 공통)이다.\n\n"
        "[거래대금 섹터 쏠림]\n" + "\n".join(fmt_c(c) for c in clusters) + "\n\n"
        "[거래대금 개별 이슈 종목]\n" + ("\n".join(fmt_i(m) for m in idio) or "- 없음") + "\n\n"
        "[어제 시장 담론 — 지배 테마(문서수)]\n" + themes + "\n\n"
        "[어제 시장 담론 — 시장구조 코멘터리]\n" + docs + "\n\n"
        "임무: 거래대금 쏠림(무엇이 움직였나)을 시장 담론(왜·무슨 얘기였나)과 **교차**해서, 개별 종목이 아니라 "
        "**시장 레벨에서 무슨 일이 있었는지**를 먼저 짚어라. 담론이 특정 사건을 지목하면 그 이름을 명시하라. "
        "거래대금 급증의 **성격**(신규 매수 랠리인지, 청산·디레버리징·반등인지)을 담론 근거로 판단하라. "
        "개별 이슈 종목에 헤드라인이 달려 있으면 그것을 그 종목의 '왜'(개별 촉매)로 삼아라.\n"
        "규율: 담론·헤드라인·구조화 팩트에 근거가 있는 것만 말하라. 헤드라인이 있으면 그 종목은 스터디 후보가 아니라 "
        "촉매를 아는 것이다. 근거가 전혀 없을 때만 스터디 후보로 돌리고, 없는 촉매를 지어내지 마라.\n"
        "JSON만 출력: {\"mood\": \"어제 시장 레벨에서 무슨 일이 있었고(담론 근거), 그게 거래대금 쏠림과 어떻게 연결되는지, "
        "성격은 무엇인지 3~5문장\", "
        "\"study_candidates\": [\"티커 — 왜 스터디해야 하는지 한 줄\"], "
        "\"share_candidates\": [\"티커/주제 — 이미 내러티브 있어 공유할 만한 것 한 줄\"]}"
    )


def _synthesize(conn, trade_date: str, signature: str, clusters, idio, movers, discourse) -> dict | None:
    """LLM 종합 — 캐시(signature 불변 재사용). 엔진 미가용이면 None(구조화 스켈레톤만)."""
    cached = conn.execute(
        "SELECT signature, synthesis_json FROM us_briefings WHERE trade_date=?", (trade_date,)).fetchone()
    if cached and cached["signature"] == signature:
        try:
            return json.loads(cached["synthesis_json"])
        except Exception:
            pass
    if llm_engine() != "claude-code":
        return None
    try:
        data = _parse_json(_call_claude_code(_synthesis_prompt(clusters, idio, movers, discourse),
                                             model="sonnet", timeout=240))
    except Exception:
        return None
    synthesis = {
        "mood": data.get("mood") or "",
        "study_candidates": data.get("study_candidates") or [],
        "share_candidates": data.get("share_candidates") or [],
    }
    conn.execute(
        "INSERT OR REPLACE INTO us_briefings (trade_date, signature, synthesis_json, model, created_at) "
        "VALUES (?,?,?, 'sonnet', datetime('now'))",
        (trade_date, signature, json.dumps(synthesis, ensure_ascii=False)))
    conn.commit()
    return synthesis


def build_briefing(force: bool = False) -> dict:
    """어젯밤 미국장 브리핑 — 구조화(LLM 0) + 종합(하루 1콜·캐시).

    반환 {status, trade_date, fetched_at, error, clusters, idiosyncratic, movers, synthesis|None}.
    LLM 미가용이어도 결정적 스켈레톤(clusters·idiosyncratic·movers)은 항상 채워진다.
    """
    lead = get_leaders(force=force)
    base = {"status": lead["status"], "trade_date": lead["trade_date"],
            "fetched_at": lead["fetched_at"], "error": lead["error"],
            "clusters": [], "idiosyncratic": [], "movers": [], "market_themes": [],
            "market_docs": [], "synthesis": None}
    if not lead["items"]:
        return base

    conn = get_connection()
    try:
        movers = _build_movers(conn, lead["items"])
        clusters = _clusters(movers)
        _flag_idiosyncratic(movers, clusters)
        _attach_headlines(conn, movers)                    # 개별 '왜' — US 원천 헤드라인(D-097)
        idio = [m for m in movers if m["flags"]]
        discourse = _gather_discourse(conn, lead["trade_date"])
        synthesis = _synthesize(conn, lead["trade_date"], _signature(lead["trade_date"], movers, discourse),
                                clusters, idio, movers, discourse) if lead["status"] == "ok" else None
    finally:
        conn.close()

    base.update({"clusters": clusters, "idiosyncratic": idio, "movers": movers,
                 "market_themes": discourse["themes"], "market_docs": discourse["docs"],
                 "synthesis": synthesis})
    return base

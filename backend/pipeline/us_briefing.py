"""어젯밤 미국장 브리핑 — 거래대금 상위를 '분위기'로 읽어준다 (docs/specs/us-briefing.md).

결정적 코어(LLM 0): 섹터 클러스터·쏠림 비중 → 개별 이슈 탐지 → 커버 종목 내러티브/언급 enrich.
**그날 시장 담론 주입(D-096)**: 지배 테마 랭킹 + 시장구조 코멘터리 문서(수급·매크로·주도섹터 링크)를 함께 종합에 넣어
거래대금 쏠림(무엇이)을 시장 레벨 촉매(왜·무슨 얘기)와 교차 — 개별 종목 경로로는 못 잡는 시장구조 사건을 잡는다.
LLM 종합(하루 1콜·캐시): 구조화 팩트 + 담론 입력 → 분위기 산문 + 스터디/공유 후보. 촉매 미상은 지어내지 않는다.

리서치를 대신하지 않고 '뭘 스터디하고 뭘 공유할지' 조준하게 하는 게 목적(펀드매니저 피드백, D-095·D-096).
"""
import hashlib
import json
import re
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
# 티커 → 우리 문서가 부르는 이름(한글 엔티티명). 커버리지(transcript_follow)와 무관하게 '왜'를 문서에서 찾기 위한 매핑.
# 실측(2026-09-09): 인텔 +9.1%의 이유("CPU 가격 10% 인상")가 키움 시황 문서에 있었지만 INTC가 팔로우 밖이라 '스터디 후보'로만 남았다.
_US_KR_NAMES = {
    "NVDA": ["엔비디아"], "MU": ["마이크론"], "SNDK": ["샌디스크"], "TSLA": ["테슬라"], "INTC": ["인텔"], "AMD": ["AMD"],
    "META": ["메타", "메타플랫폼스"], "AVGO": ["브로드컴"], "AAPL": ["애플"], "MSFT": ["마이크로소프트", "MS"], "GOOGL": ["알파벳", "구글"],
    "GOOG": ["알파벳", "구글"], "AMZN": ["아마존"], "CRWV": ["코어위브"], "NBIS": ["네비우스"], "ORCL": ["오라클"], "PLTR": ["팔란티어"],
    "SPCX": ["스페이스X"], "BE": ["블룸에너지", "블룸 에너지"], "LITE": ["루멘텀"], "DELL": ["델"], "TSM": ["TSMC"], "SMCI": ["슈퍼마이크로"],
    "ANET": ["아리스타"], "MRVL": ["마벨"], "COHR": ["코히런트"], "VRT": ["버티브"], "ETN": ["이튼"], "IREN": ["아이렌", "IREN"],
    "NFLX": ["넷플릭스"], "COIN": ["코인베이스"], "HOOD": ["로빈후드"], "UNH": ["유나이티드헬스"], "JPM": ["JP모건"], "LLY": ["일라이릴리"],
}
_MENTION_HOURS = 40      # 상위 종목 '왜' 탐색 창 — 미국장 마감(05:00 KST) 전후 하루 반
_MENTIONS_PER_MOVER = 3
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


NARRATIVE_GIST_CHARS = 340


def _narrative_gist(body: str | None) -> str | None:
    """내러티브 본문에서 **주장의 실체**를 뽑는다 (D-114).

    제목만 넘기면 브리핑이 자기충족적이지 않다 — "'에이전트가 실제로 일을 하기 시작하면
    비용은 누가 대나' 내러티브 있음"을 읽어도 그 서사가 무엇을 주장하는지 모른다.
    본문 최상단 `## 3줄 요약`(생성 규약상 항상 존재)을 실체로 쓰고, 없으면 앞부분을 잘라 쓴다.
    """
    if not body:
        return None
    text = body
    if "## 3줄 요약" in body:
        rest = body.split("## 3줄 요약", 1)[1]
        text = rest.split("\n## ", 1)[0]
    lines = [ln.strip().lstrip("-*• ").strip() for ln in text.splitlines() if ln.strip()]
    gist = " / ".join(ln for ln in lines if not ln.startswith("#"))
    return gist[:NARRATIVE_GIST_CHARS] or None


def _resolve_any(conn, ticker: str) -> tuple[list[int], list[str]]:
    """티커 → (엔티티 id들, 문서에서 부르는 이름들). transcript_follow·ADR 본체·한글 별칭표 순으로 넓게 잡는다."""
    us_eid, _ = resolve_us(conn, ticker)
    home_eid = _home_entity_id(conn, ticker)
    names = list(_US_KR_NAMES.get((ticker or "").upper(), []))
    ids = [e for e in [us_eid, home_eid] if e]
    for nm in names:
        row = conn.execute("SELECT id FROM entities WHERE type='company' AND name=? LIMIT 1", (nm,)).fetchone()
        if row and row["id"] not in ids:
            ids.append(row["id"])
    if home_eid:
        nm = _ADR_HOME.get((ticker or "").upper())
        if nm and nm not in names:
            names.append(nm)
    return ids, [n for n in names if len(n) >= 2]


def _recent_mentions(conn, ids: list[int], names: list[str], hours: int = _MENTION_HOURS,
                     k: int = _MENTIONS_PER_MOVER) -> list[dict]:
    """최근 문서에서 이 종목을 언급한 문장 — 엔티티 링크 또는 이름 부분일치. LLM 0.
    '무슨 일이 있었나'를 문서의 말로 옮기기 위한 재료(라벨이 아니라 사건)."""
    if not ids and not names:
        return []
    from pipeline.chat_tools import _mention_sentences
    conds, params = [], []
    if ids:
        conds.append(f"rd.id IN (SELECT doc_id FROM entity_links WHERE entity_id IN ({','.join('?' * len(ids))}))")
        params += ids
    for nm in names[:3]:
        conds.append("(rd.title LIKE '%'||?||'%' OR rd.markdown LIKE '%'||?||'%')")
        params += [nm, nm]
    rows = conn.execute(f"""
        SELECT rd.id, rd.title, rd.published_at, rd.source_type, substr(rd.markdown,1,20000) body
        FROM raw_documents rd WHERE rd.published_at >= datetime('now', ?) AND length(rd.markdown) >= 80
          AND ({' OR '.join(conds)}) ORDER BY rd.published_at DESC LIMIT 12""", (f"-{hours} hours", *params)).fetchall()
    out = []
    for r in rows:
        sent = None
        for nm in names:
            got = _mention_sentences(r["body"] or "", nm, k=2, width=240)   # 첫 언급은 종목 나열일 때가 많다 — 두 창을 이어 붙인다
            if got:
                sent = " … ".join(got)
                break
        if not sent and names:
            continue           # 엔티티 링크만 있고 이름이 본문에 없으면 문장을 못 뽑는다 — 건너뜀
        out.append({"doc_id": r["id"], "title": (r["title"] or "")[:60], "when": (r["published_at"] or "")[:16],
                    "source_type": r["source_type"], "sentence": sent or ""})
        if len(out) >= k:
            break
    return out


def _enrich_coverage(conn, ticker: str) -> dict:
    """우리 커버리지 — 엔티티(US·ADR 본체·한글 별칭) 해소 시 최근 언급수·언급 문장·걸린 내러티브. 없으면 uncovered."""
    ids, names = _resolve_any(conn, ticker)
    us_eid = ids[0] if ids else None
    home_eid = None
    if not ids:
        return {"coverage": "uncovered", "entity_id": None, "mentions_3d": 0,
                "narrative": None, "narrative_gist": None, "mentions": []}
    ph = ",".join("?" * len(ids))
    m = conn.execute(
        f"SELECT count(DISTINCT el.doc_id) n FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        f"WHERE el.entity_id IN ({ph}) AND rd.published_at >= datetime('now','-3 days')", ids).fetchone()
    nar = conn.execute(
        f"SELECT n.title t, n.body b FROM entity_relations r JOIN narratives n ON n.id=r.narrative_id "
        f"WHERE (r.src_id IN ({ph}) OR r.dst_id IN ({ph})) AND r.narrative_id IS NOT NULL "
        f"ORDER BY n.id DESC LIMIT 1", ids + ids).fetchone()
    return {"coverage": "covered", "entity_id": us_eid or home_eid,
            "mentions_3d": m["n"] if m else 0,
            "narrative": nar["t"] if nar else None,
            "narrative_gist": _narrative_gist(nar["b"]) if nar else None,
            "mentions": _recent_mentions(conn, ids, names)}


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
            m["headlines"] = _relevant_headlines(m, get_news(conn, m["ticker"]))


def _relevant_headlines(m: dict, items: list[dict]) -> list[dict]:
    """티커·회사명(영문 첫 토큰·한글 별칭)이 제목에 없는 헤드라인은 버린다 — yfinance 뉴스는 시장 일반 기사가 섞인다
    (실측: 엔비디아에 버텍스 파마 기사)."""
    toks = {m["ticker"].lower()}
    first = (m.get("name") or "").split(" ")[0].strip(",.").lower()
    if len(first) >= 4:
        toks.add(first)
    toks |= {n.lower() for n in _US_KR_NAMES.get(m["ticker"].upper(), [])}
    out = [h for h in items if any(t in (h.get("title") or "").lower() for t in toks)]
    return out[:3]


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
    # 문서유형 메타 라벨(산업동향·실적분석·수급…)은 지배 테마가 아니다 — 제외 없이는 상위를
    # 독식해 '무슨 얘기였나'를 가린다(실측: 산업동향 57건이 반도체 36건보다 위에 올라왔다). D-114
    from pipeline.signals import THEME_STOPWORDS
    sw = ",".join("?" * len(THEME_STOPWORDS))
    themes = [{"name": r["name"], "count": r["c"]} for r in conn.execute(
        f"SELECT e.name, count(DISTINCT rd.id) c FROM entity_links el "
        f"JOIN raw_documents rd ON rd.id=el.doc_id JOIN entities e ON e.id=el.entity_id "
        f"WHERE substr(rd.published_at,1,10)=? AND e.type IN ('theme','sector') "
        f"AND e.name NOT IN ({sw}) "
        f"GROUP BY e.id ORDER BY c DESC LIMIT ?",
        (day, *THEME_STOPWORDS, _DISCOURSE_THEMES)).fetchall()]
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


# 국면 판정 임계 — 지표마다 단위·변동성이 달라(10Y 4.68 vs BTC 63,350) 절대·상대 변화율로는
# 한 기준을 못 쓴다. **자체 관측 범위(hi-lo) 대비 드리프트**로 재면 스케일 무관해진다.
MACRO_FLAT = 0.15       # 범위의 15% 미만 이동 = 횡보
MACRO_STRONG = 0.45     # 범위의 45% 이상 이동 = 뚜렷한 방향
MACRO_MIN_OBS = 8       # 국면 판정 최소 관측 수
MACRO_BAND_EDGE = 25    # 밴드 상·하단으로 볼 백분위


def _macro_regime(series: list[float]) -> dict | None:
    """매크로 지표의 **국면**을 결정적으로 판정 (LLM 0, D-114).

    사용자 지적: "유동성·M2·신용은 당장 오늘의 전일 대비 변화보다 '지금이 어떤 국면인가'라는
    추이가 중요하다 — 이런 매크로 요인들은 장기 시계열로 시장에 영향을 미친다."
    그래서 단기 델타(D-101의 5관측 전 대비)와 **별도로** 구간 국면을 함께 준다.

    측정: ①드리프트 = (최근 1/3 평균 − 초기 1/3 평균) / 관측범위 → 스케일 무관한 방향·강도
          ②밴드 위치 = 현재값이 관측 범위의 어디쯤(0=저점, 100=고점)
    """
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < MACRO_MIN_OBS:
        return None
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    k = max(2, len(vals) // 3)
    early = sum(vals[:k]) / k
    late = sum(vals[-k:]) / k
    drift = (late - early) / rng if rng else 0.0
    band = round((vals[-1] - lo) / rng * 100) if rng else 50

    mag = abs(drift)
    if mag < MACRO_FLAT:
        label = "횡보"
    else:
        strength = "뚜렷한 " if mag >= MACRO_STRONG else "완만한 "
        label = f"{strength}{'상승' if drift > 0 else '하락'} 국면"
    where = ("밴드 상단" if band >= 100 - MACRO_BAND_EDGE else
             "밴드 하단" if band <= MACRO_BAND_EDGE else "밴드 중단")
    span_pct = round((vals[-1] - vals[0]) / abs(vals[0]) * 100, 2) if vals[0] else None
    return {"label": label, "band_pos": band, "where": where,
            "obs": len(vals), "span_pct": span_pct}


def _last_move(series: list[float]) -> dict | None:
    """**직전 관측 대비** 방향 (D-128).

    왜 필요한가: 재료의 '단기'는 D-101의 5관측 전 대비다. 그것만 주면 모델이 며칠 누적치를
    '그날의 방아쇠'로 쓴다(실측 8/18: 10년물 5일 누적 +0.64%를 근거로 "방아쇠는 금리"라고
    썼는데 그날 10년물은 4.72→4.71로 내렸다). 방아쇠라고 부를 근거는 그날 방향이므로
    5관측 델타와 **별도 라벨로** 직전 관측 대비를 함께 준다.
    숫자 산출 주체는 D-101 하나로 유지한다 — 여기서 만드는 건 경쟁하는 델타가 아니라 방향이다.
    """
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < 2 or not vals[-2]:
        return None
    pct = (vals[-1] - vals[-2]) / abs(vals[-2]) * 100
    return {"pct": round(pct, 2),
            "dir": "상승" if pct > 0.01 else "하락" if pct < -0.01 else "보합"}


_RATE_KEYS = ("us2y", "us10y")


def _rate_bp(item: dict) -> dict | None:
    """금리 변화는 %가 아니라 bp (D-206). 실측: 10Y 5.24의 '+1.16%'는 약 +6bp인데 %로 나가 과장돼 읽혔다.
    구간은 D-101과 같은 5관측 전 대비와 직전 관측 대비."""
    vals = [v for v in (item.get("series") or []) if v is not None]
    if len(vals) < 2:
        return None
    return {"last": round((vals[-1] - vals[-2]) * 100, 1),
            "short": round((vals[-1] - vals[-6]) * 100, 1) if len(vals) >= 6 else None}


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
              "group": i.get("group_label"), "group_key": i.get("group"),
              "regime": _macro_regime(i.get("series") or []),
              "last_move": _last_move(i.get("series") or []),
              "bp": _rate_bp(i) if i.get("key") in _RATE_KEYS else None}
             for i in m.get("items", []) if i.get("change_pct") is not None]
    sig = m.get("signal") or {}
    return {"as_of": m.get("as_of"), "items": items, "lookback": "5관측 전 대비",
            # _read_signal은 as_of를 반환하지 않는다 — 애초에 매크로 as_of로 조회한 행이므로 동일
            "signal": {"as_of": m.get("as_of"), "signal": sig.get("signal"),
                       "headline": sig.get("headline")} if sig.get("signal") else None,
            "degraded": m.get("degraded") or []}


# 어젯밤 매크로 이슈 (D-206) — 지정 소스에서 이슈를 뽑고, 인용이 원문에 그대로 있는 것만 남긴다.
# 사용자 지정: 매크로·전략 텔레그램 채널 + 미국 주요 매체·Fed RSS. 트럼프 발언 채널(goddessTTF)은 제외.
MACRO_CHANNELS = ("cahier_de_market", "Macrojunglemicrolens", "MacroAllocation", "yieldnspread",
                  "samsung_macro", "huhjae", "hedgecat0301")
_MACRO_DOCS = 30          # 텔레그램 글 상한(최신순)
_MACRO_DOC_CHARS = 2500   # 글당 원문 길이 상한
_MACRO_NEWS = 80          # 헤드라인 상한(최신순)
_MACRO_ISSUES = 5
_QUOTE_MIN = 8            # 이보다 짧은 인용은 검증 의미가 없다


def _macro_window(conn, trade_date: str) -> tuple[str, str]:
    """직전 거래일 미국장 마감(UTC 20:00) ~ 기준일 다음날 UTC 00:00(KST 09:00).

    날짜 문자열 일치로 자르면 주말·휴장 사이 이슈(금 마감 후 발표 등)가 빠진다. 직전 거래일은
    us_movers 스냅샷에서 찾고, 없으면 하루 전. 창이 과하게 길어지지 않게 4일로 자른다.
    """
    from datetime import date, timedelta
    d = date.fromisoformat(trade_date[:10])
    row = conn.execute("SELECT max(trade_date) p FROM us_movers WHERE trade_date < ?", (trade_date,)).fetchone()
    prev = date.fromisoformat(row["p"][:10]) if row and row["p"] else d - timedelta(days=1)
    prev = max(prev, d - timedelta(days=4))
    return f"{prev.isoformat()}T20:00:00+00:00", f"{(d + timedelta(days=1)).isoformat()}T00:00:00+00:00"


def _gather_macro_sources(conn, trade_date: str) -> list[dict]:
    """창 안의 지정 채널 글(T*) + 매체·Fed 헤드라인(N*). text = 인용 검증 대상 원문."""
    from pipeline.macro_news import read_window
    start, end = _macro_window(conn, trade_date)
    ph = ",".join("?" * len(MACRO_CHANNELS))
    tg = conn.execute(
        f"SELECT rd.id, rd.title, rd.url, rd.published_at, rd.markdown, "
        f"       COALESCE(tc.display_name, tc.channel_name) publisher "
        f"FROM raw_documents rd JOIN telegram_channels tc ON rd.source_id LIKE tc.channel_name || '/%' "
        f"WHERE rd.source_type='telegram' AND tc.channel_name IN ({ph}) "
        f"  AND rd.published_at >= ? AND rd.published_at < ? AND length(rd.markdown) >= 40 "
        f"ORDER BY rd.published_at DESC LIMIT ?", (*MACRO_CHANNELS, start, end, _MACRO_DOCS)).fetchall()
    out = [{"ref": f"T{i}", "kind": "telegram", "publisher": r["publisher"], "title": (r["title"] or "")[:120],
            "url": r["url"], "doc_id": r["id"], "published_at": r["published_at"],
            "text": (r["markdown"] or "")[:_MACRO_DOC_CHARS]} for i, r in enumerate(tg, 1)]
    for i, n in enumerate(read_window(conn, start, end)[:_MACRO_NEWS], 1):
        out.append({"ref": f"N{i}", "kind": n["kind"], "publisher": n["publisher"], "title": n["title"],
                    "url": n["url"], "doc_id": None, "published_at": n["published_at"],
                    "text": n["title"] + ("\n" + n["summary"] if n["summary"] else "")})
    return out


def _macro_issue_prompt(trade_date: str, sources: list[dict]) -> str:
    def fmt(s):
        body = s["text"].strip()
        return f"<{s['ref']} | {s['publisher']} | {(s['published_at'] or '')[:16]}Z>\n{body}\n</{s['ref']}>"
    tg = "\n\n".join(fmt(s) for s in sources if s["kind"] == "telegram") or "(없음)"
    news = "\n\n".join(fmt(s) for s in sources if s["kind"] != "telegram") or "(없음)"
    return (
        f"당신은 미국장 매크로 담당 애널리스트다. {trade_date} 미국장 전후에 나온 자료에서 "
        "**어젯밤 미국 시장 전체에 영향을 준 매크로·정책·정치·금융 이슈**를 최대 5개 뽑는다.\n\n"
        f"[국내 매크로·전략 텔레그램 채널 글 (T*)]\n{tg}\n\n"
        f"[미국 주요 매체·Fed 헤드라인과 요약 (N*)]\n{news}\n\n"
        "규칙:\n"
        "- 개별 기업 실적·종목 뉴스는 제외한다. 시장 전체(금리·달러·유가·신용·지수)에 파급된 경우만 넣는다.\n"
        "- 중요도 순으로 정렬한다: 여러 출처가 다룬 것, 가격 반응이 언급된 것이 앞이다. 미국과 무관한 해외 지역 뉴스는 "
        "미국 시장 반응이 언급될 때만 넣는다.\n"
        "- what은 출처에 있는 사실만 1~2문장 한국어로. 출처에 없는 수치·일정·인과를 보태지 마라.\n"
        "- reaction은 출처가 언급한 시장 반응(예: '10년물 금리 상승', '금 7주 저점'). 없으면 빈 문자열.\n"
        "- sources의 quote는 해당 출처 원문에서 **글자 그대로 복사한** 연속 구간(15~150자)이다. 번역·요약·말줄임 금지 — "
        "영문 출처는 영문 그대로 복사한다. 원문과 한 글자라도 다르면 그 출처는 버려진다.\n"
        "- 이슈가 없으면 빈 배열을 낸다. 지어내지 마라.\n\n"
        "JSON만 출력: {\"issues\": [{\"title\": \"짧은 한국어 제목\", \"what\": \"…\", \"reaction\": \"…\", "
        "\"sources\": [{\"ref\": \"N3\", \"quote\": \"원문 그대로\"}]}]}"
    )


_QUOTE_TR = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})


def _norm_quote(text: str) -> str:
    return " ".join((text or "").translate(_QUOTE_TR).split())


def _verify_issues(raw: list, sources: list[dict]) -> list[dict]:
    """인용 검증 — quote가 해당 출처 원문에 공백·따옴표 정규화 후 그대로 있어야 채택 (Weekly D-173 규율 차용).
    검증된 출처가 하나도 없는 이슈는 버린다."""
    by_ref = {s["ref"]: s for s in sources}
    out = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        refs = []
        for c in it.get("sources") or []:
            if not isinstance(c, dict):
                continue
            src = by_ref.get(str(c.get("ref") or "").strip())
            q = _norm_quote(c.get("quote")).strip("\"' ")
            if src and len(q) >= _QUOTE_MIN and q in _norm_quote(src["text"]) and src["ref"] not in refs:
                refs.append(src["ref"])
        if refs:
            out.append({"title": str(it["title"])[:80], "what": str(it.get("what") or "")[:400],
                        "reaction": str(it.get("reaction") or "")[:200], "refs": refs})
        if len(out) >= _MACRO_ISSUES:
            break
    return out


def _macro_issues(conn, trade_date: str) -> dict:
    """어젯밤 매크로 이슈 {issues, sources(ref→메타), gaps} — 버튼·아침 잡 경로에서만 호출.

    sonnet 1콜, 프롬프트 해시 캐시 — 창 안의 원문이 안 바뀌면 재호출하지 않는다.
    """
    empty = {"issues": [], "sources": {}, "gaps": []}
    sources = _gather_macro_sources(conn, trade_date)
    if not sources:
        return {**empty, "gaps": ["지정 매크로 소스에 해당 시간창 자료 없음"]}
    prompt = _macro_issue_prompt(trade_date, sources)
    signature = _prompt_signature(trade_date, prompt)
    row = conn.execute("SELECT signature, issues_json FROM us_macro_issues WHERE trade_date=?",
                       (trade_date,)).fetchone()
    if row and row["signature"] == signature:
        return json.loads(row["issues_json"])
    if llm_engine() != "claude-code":
        return {**empty, "gaps": ["LLM 미가용 — 매크로 이슈 추출 생략"]}
    try:
        data = _parse_json(_call_claude_code(prompt, model="sonnet", timeout=300))
    except Exception as e:  # noqa: BLE001
        print(f"[us_briefing] 매크로 이슈 추출 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {**empty, "gaps": ["매크로 이슈 추출 실패"]}
    raw = data.get("issues") if isinstance(data, dict) else None
    issues = _verify_issues(raw, sources)
    dropped = len(raw or []) - len(issues)
    if dropped > 0:
        print(f"[us_briefing] 매크로 이슈 {dropped}개 인용 검증 실패로 제외", flush=True)
    used = {r for it in issues for r in it["refs"]}
    result = {"issues": issues,
              "sources": {s["ref"]: {k: s[k] for k in ("kind", "publisher", "title", "url", "doc_id", "published_at")}
                          for s in sources if s["ref"] in used},
              "gaps": []}
    conn.execute("INSERT OR REPLACE INTO us_macro_issues (trade_date, signature, issues_json, created_at) "
                 "VALUES (?,?,?, datetime('now'))", (trade_date, signature, json.dumps(result, ensure_ascii=False)))
    conn.commit()
    return result


def _prompt_signature(trade_date: str, prompt: str) -> str:
    """재생성 게이트 = **프롬프트 자체의 해시** (D-114 — D-112의 '입력 날짜만' 방식 번복).

    왜 바꿨나: 날짜만 해싱하면 **프롬프트 템플릿을 고쳐도 캐시가 적중해 옛 산출물이 그대로 나온다**
    (실측: 담론 테마 필터·매크로 국면 지시를 넣었는데 이전 종합이 반환됐다). 또 같은 날 데이터가
    수정돼도 감지하지 못한다.

    비용 걱정이 없는 이유: 프롬프트는 DB 상태의 결정적 함수다 — 데이터가 안 바뀌면 프롬프트가
    같고 따라서 캐시가 적중한다. 즉 '진짜 변화 1회당 재종합 1회'로, 날짜 방식보다 정확하면서
    비용은 동일하다.
    """
    return hashlib.sha256((trade_date + "|" + prompt).encode()).hexdigest()


def _synthesis_prompt(clusters, idio, movers, discourse, indices, macro, macro_issues, trade_date) -> str:
    """2문단 브리핑 프롬프트 (D-206) — 매크로 브리핑 + 거래대금 기반 기업 이슈 브리핑.

    D-112의 4섹션에서 ① 지수 문단(카드 상단 타일과 중복)과 ④ 섹터 비중 흐름 문단(사용자 판단:
    쓸모 낮음)을 걷어냈다. 매크로 문단은 지표 읽기가 아니라 **지정 소스에서 검증된 이슈**가 주어이고,
    지표는 그 이슈의 시장 반응 근거로만 쓴다.
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
        gist = f"\n    (내러티브 요지: {m['narrative_gist']})" if m.get("narrative_gist") else ""
        ment = ""
        if m.get("mentions"):
            ment = "\n    수집 문서 언급(이 종목에 무슨 일이 있었나 — 여기 있는 사건을 그대로 옮겨 쓸 것):\n" + "\n".join(
                f"      · [{x['source_type']} {x['when']}] {x['title']}: \"{x['sentence'][:200]}\"" for x in m["mentions"])
        return (f"- {m['ticker']} ({m['name']}): {', '.join(m['flags'])} · 최근언급 {m['mentions_3d']}건 "
                f"· 관련내러티브: {cov}{gist}{head}{ment}")

    idx = "- 없음"
    if indices.get("items"):
        same = indices["as_of"] == trade_date
        idx = (f"({indices['as_of']} 종가"
               + ("" if same else f" — 거래대금 기준일 {trade_date}와 다름, 반드시 날짜를 밝힐 것")
               + ")\n" + "\n".join(
                   f"- {i['name']}: {i['close']:,} ({i['change_pct']:+.2f}%)" for i in indices["items"]))

    # 매크로 이슈 — 출처 번호 S1..Sn은 이슈 순서대로 매긴다(본문 표식 → 화면 링크)
    snum = _source_numbers(macro_issues)
    iss = "- 없음 (지정 매크로 소스에서 검증된 이슈가 없다)"
    if macro_issues.get("issues"):
        srcs = macro_issues.get("sources") or {}
        iss = "\n".join(
            f"- {it['title']}: {it['what']}"
            + (f" · 시장 반응: {it['reaction']}" if it.get("reaction") else "")
            + "\n    출처: " + ", ".join(
                f"[S{snum[r]}] {srcs.get(r, {}).get('publisher', '?')}" for r in it["refs"] if r in snum)
            for it in macro_issues["issues"])

    mac = "- 없음"
    if macro.get("items"):
        # 구조 지표(유동성·신용)는 국면만, 가격 지표는 국면 + 그날 방향 (D-114·D-128)
        slow = [i for i in macro["items"] if i.get("group_key") in ("liquidity", "credit")]
        fast = [i for i in macro["items"] if i.get("group_key") not in ("liquidity", "credit")]

        def fmt_m(i, with_short: bool):
            r = i.get("regime") or {}
            reg = f"{r['label']} · {r['where']}" if r else "관측 부족"
            if not with_short:
                return f"  - {i['name']}: {i['value']:,} · {reg}"
            bp, lm = i.get("bp"), i.get("last_move")
            if bp:                                    # 금리는 bp (D-206)
                day = f"그날 {bp['last']:+.1f}bp" + (f" · 5관측 {bp['short']:+.1f}bp" if bp.get("short") is not None else "")
            else:
                day = (f"그날 {lm['pct']:+.2f}% · " if lm else "") + f"5관측 {i['change_pct']:+.2f}%"
            return f"  - {i['name']}: {i['value']:,} ({day}) · {reg}"

        mac = f"({macro.get('as_of')} 기준)\n· 구조 지표 — 국면만\n"
        mac += ("\n".join(fmt_m(i, with_short=False) for i in slow) or "  - 없음")
        mac += "\n· 가격 지표 — '그날'이 방향 판단의 기준, 5관측은 누적 배경\n"
        mac += ("\n".join(fmt_m(i, with_short=True) for i in fast) or "  - 없음")
        if macro.get("degraded"):
            mac += f"\n- (수집 실패로 빠진 지표: {', '.join(macro['degraded'])})"

    themes = ", ".join(f"{t['name']}({t['count']})" for t in discourse.get("themes", [])) or "없음"
    docs = "\n".join(
        f"- [{d['source_type']}] {d['title']}: {(d['excerpt'] or '').strip()[:180]}"
        for d in discourse.get("docs", [])) or "- 없음"

    return (
        "당신은 미국장 마감 후 아침 브리핑을 쓰는 애널리스트다. 아래 재료로 2개 문단을 쓴다.\n\n"
        f"[A. 지수 마감]\n{idx}\n\n"
        f"[B. 어젯밤 매크로 이슈 — 지정 소스에서 인용 검증을 통과한 것, 중요도 순]\n{iss}\n\n"
        f"[C. 매크로 지표 — 이슈의 시장 반응을 확인하는 근거]\n{mac}\n\n"
        f"[D-1. 거래대금 섹터 쏠림]\n" + "\n".join(fmt_c(c) for c in clusters) + "\n\n"
        f"[D-2. 거래대금 개별 이슈 종목]\n" + ("\n".join(fmt_i(m) for m in idio) or "- 없음") + "\n\n"
        f"[D-3. 그날 시장 담론 — 지배 테마(문서수)]\n{themes}\n\n"
        f"[D-4. 그날 시장 담론 — 시장구조 코멘터리]\n{docs}\n\n"
        "임무 — 두 문단. 화면에서 소제목 없이 이어 붙여 한 편의 글로 읽힌다(D-114). "
        "항목 이름을 문단 앞에 달지 말고 자연스럽게 넘어가라. 지수 수치는 화면 상단에 따로 보이니 나열하지 마라.\n"
        "① drivers(매크로) — **4~6문장.** 첫 문장은 지수 마감의 성격을 한 구절로 짚고 가장 중요한 매크로 이슈로 들어간다. "
        "[B]의 이슈 2~3개를 **사건 중심으로** 쓴다: 무슨 일이 있었나 → 시장이 어떻게 반응했나([C]의 수치로 확인, "
        "금리는 bp로) → 누가 그렇게 봤나. 지표를 이슈와 무관하게 나열하지 마라. 구조 지표(유동성·신용)는 "
        "필요할 때 마지막 한 문장의 배경으로만 국면·위치를 말한다.\n"
        "   **출처 표식 필수**: [B]의 이슈에서 가져온 문장 끝에 그 이슈의 출처 번호를 `[S1]`, `[S2][S4]`처럼 붙인다. "
        "[B]에 없는 번호를 만들지 마라. [C] 지표만으로 쓴 문장에는 표식을 달지 않는다.\n"
        "   **귀속은 출처 이름으로만**: [B]의 출처 이름은 채널·매체 이름이지 글쓴이가 아니다(한 채널에 다른 사람 글이 "
        "올라온다). 'OO 채널은', '블룸버그는'처럼 쓰고 특정인의 견해로 단정하지 마라. 여러 출처가 함께 뒷받침한 사실을 "
        "한 곳의 견해로 쓰지 마라.\n"
        "   [B]가 비었으면 '지정 매크로 소스에서 확인된 이슈가 없다'고 밝히고 [C]의 국면으로 2문장만 쓴다. "
        "재료에 없는 이벤트(FOMC·CPI 등)를 지어내지 마라.\n"
        "② issues(기업) — **3~4문장.** 중요한 것만 남겨라: 쏠린 섹터 1~2개, 그룹으로 안 풀리는 개별 종목 "
        "**가장 중요한 2~3개**, 그리고 거래대금 급증의 **성격**(신규 매수 랠리인지, 청산·디레버리징·되돌림인지). "
        "종목을 빠짐없이 훑지 마라 — 덜 중요한 건 버리고 스터디 후보로 넘겨라. "
        "**개별 종목은 라벨이 아니라 사건으로 쓴다**: '단일 촉매 확인'·'촉매 실체 불명' 같은 판정어만 쓰지 말고, "
        "수집 문서 언급·헤드라인에 있는 **무슨 일이 있었는지**(예: 'CPU 가격 10% 인상 발표', '네비우스 실적 발표에 동반 상승')를 그 종목 문장에 넣어라. "
        "언급도 헤드라인도 없을 때만 '수집 문서·헤드라인에 촉매 없음'이라고 쓴다. "
        "**내러티브를 끌어올 때는 제목만 던지지 마라(D-114).** `(내러티브 요지: …)`에 실체가 "
        "있으니 **그 요지가 주장하는 바를 한 구절로 풀어** 브리핑만 읽고도 내용이 파악되게 하라. "
        "[B]의 이슈에 있는 내용을 쓰면 여기서도 같은 `[S n]` 표식을 붙인다.\n\n"
        "공통 규율: 근거 있는 것만. 촉매를 모르면 지어내지 말고 스터디 후보로 돌려라. "
        "분량 예산을 넘기지 마라 — 길게 쓰는 것보다 버리는 것이 어렵고 중요하다.\n"
        "\n"
        "톤 규율 (D-128 — 사용자 피드백, 위반이 반복 관측됨):\n"
        "- **하루치를 구조 전환의 시초로 읽지 마라.** 대부분의 하루는 위험 인식 조정에 따른 "
        "**자본 재배치**이고 수급에 따라 며칠 안에 반대로 움직인다. '임계점', '자금줄', '균열', "
        "'국면 전환의 신호' 같은 서술은 그것을 뒷받침하는 재료가 있을 때만 쓴다.\n"
        "- **움직임의 원인은 그날 방향으로만 판정하라.** 5관측 누적이 올랐어도 '그날'이 하락이면 그 지표를 "
        "그날 하락의 원인으로 쓸 수 없다 — 그때는 '높은 수준이 이어지고 있다'고 쓴다.\n"
        "- **자금 이탈과 재배치를 구분하라.** 거래대금 비중이 유지·확대되는데 등락만 꺾였으면 "
        "'자금이 이탈했다'고 쓰지 마라(차익실현·재평가).\n"
        "- **한 곳의 견해를 시장의 합의나 논쟁으로 부풀리지 마라.** 한 매체·채널만 말한 것은 "
        "'누가 어디서 말했다'로 귀속해 쓴다.\n"
        "- **내부 판정 어휘를 쓰지 마라**: '방아쇠', '배경 조건', '밴드 상단/하단', '5관측' 같은 재료의 용어는 "
        "독자에게 뜻이 없다. '최근 범위의 위쪽', '며칠째 오름세'처럼 풀어 쓴다.\n"
        "- **구어체·수사 금지.** 직접적인 평서문으로 쓴다. 비유·감탄·강조 부사를 덜어내라.\n"
        "- **투자 대응·매매 처방을 쓰지 마라.** 비중 조절·매수·헤지 조언은 범위 밖이다(스터디·공유 후보는 그대로 남긴다).\n"
        "- **재료 구획 이름을 본문에 노출하지 마라.** '[C]를 보면'이 아니라 내용으로 지칭하라. "
        "허용되는 괄호 표식은 출처 번호 `[S n]`뿐이다.\n"
        "JSON만 출력: {\"drivers\": \"…\", \"issues\": \"…\", "
        "\"movers_why\": [{\"ticker\": \"INTC\", \"why\": \"+9.1% — 무슨 일(출처 종류). 사건이 없으면 '촉매 없음'\"}] (개별 이슈 종목 전부, 각 60자 이내), "
        "\"study_candidates\": [\"티커 — 왜 스터디해야 하는지 한 줄\"], "
        "\"share_candidates\": [\"티커/주제 — 이미 내러티브 있어 공유할 만한 것 한 줄\"]}"
    )


def _source_numbers(macro_issues: dict) -> dict:
    """이슈 출처 ref(T3·N12) → 프롬프트 번호 S1.. (이슈 순서, 첫 등장 순)."""
    out: dict[str, int] = {}
    for it in macro_issues.get("issues") or []:
        for r in it["refs"]:
            out.setdefault(r, len(out) + 1)
    return out


_CITE_RE = re.compile(r"\[\s*S\s*\d+(?:\s*[,，]\s*S?\s*\d+)*\s*\]")


def _link_citations(texts: list[str], macro_issues: dict) -> tuple[list[str], list[dict]]:
    """본문들의 `[S n]` 표식 → 화면 번호 `[1]`..(두 문단 통틀어 등장 순 재번호) + 출처 목록 (D-206).

    기업 문단도 매크로 이슈 출처(예: 오라클 불가항력 보도)를 인용할 수 있어 번호를 공유한다.
    프롬프트에 없던 번호는 지운다(지어낸 출처를 링크로 만들지 않는다).
    """
    by_num = {n: ref for ref, n in _source_numbers(macro_issues).items()}
    srcs = macro_issues.get("sources") or {}
    order: dict[str, int] = {}

    def repl(m):
        nums = [int(x) for x in re.findall(r"\d+", m.group(0))]
        refs = [by_num[n] for n in nums if n in by_num and by_num[n] in srcs]
        return "".join(f"[{order.setdefault(r, len(order) + 1)}]" for r in dict.fromkeys(refs))

    out = []
    for text in texts:
        linked = re.sub(r"\s+(?=\[\s*S\s*\d)", "", text or "")     # 표식 앞 공백은 붙인다
        out.append(_CITE_RE.sub(repl, linked))
    return out, [{"n": n, **srcs[ref]} for ref, n in order.items()]


# index_summary는 D-206 이전 행 호환용(새 종합은 비워 둔다)
SYNTH_SECTIONS = ("index_summary", "drivers", "issues")


def _normalize_synthesis(data: dict) -> dict:
    """저장/반환 형태 통일 + 구 스키마 호환.

    D-112 이전 행은 `mood` 하나뿐이다 — 그 시절 산문은 지금의 issues에 해당하므로
    거기로 흘려보내 과거 브리핑도 그대로 읽히게 한다(히스토리를 깨지 않는다).
    D-206 이전 행의 `flow` 문단은 폐지된 구성이라 읽지 않는다.
    """
    out = {k: (data.get(k) or "") for k in SYNTH_SECTIONS}
    if not out["issues"] and data.get("mood"):
        out["issues"] = data["mood"]
    out["study_candidates"] = data.get("study_candidates") or []
    out["share_candidates"] = data.get("share_candidates") or []
    out["movers_why"] = [x for x in (data.get("movers_why") or []) if isinstance(x, dict) and x.get("ticker")]
    out["sources"] = [x for x in (data.get("sources") or []) if isinstance(x, dict) and x.get("n")]
    out["source_gaps"] = [x for x in (data.get("source_gaps") or []) if isinstance(x, str)]
    return out


def _synthesize(conn, trade_date: str, clusters, idio, movers,
                discourse, indices, macro, macro_issues, feed_gaps: list[str]) -> dict | None:
    """LLM 종합 — 프롬프트 해시로 캐시 판정. 엔진 미가용이면 None(구조화 스켈레톤만)."""
    prompt = _synthesis_prompt(clusters, idio, movers, discourse, indices, macro, macro_issues, trade_date)
    signature = _prompt_signature(trade_date, prompt)
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
        data = _parse_json(_call_claude_code(prompt, model="sonnet", timeout=300))
    except Exception as e:  # noqa: BLE001 — 원인을 로그로 남긴다(구 silent-None 대비)
        print(f"[us_briefing] 종합 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return None
    (data["drivers"], data["issues"]), data["sources"] = _link_citations(
        [data.get("drivers") or "", data.get("issues") or ""], macro_issues)
    data["source_gaps"] = list(macro_issues.get("gaps") or []) + feed_gaps
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
    """어젯밤 미국장 브리핑 — 구조화(LLM 0) + 매크로 이슈 추출·2문단 종합(각 sonnet 1콜·캐시, D-206).

    반환 {status, trade_date, fetched_at, error, stale_days, clusters, idiosyncratic,
          movers, market_themes, market_docs, indices, macro, synthesis|None}.
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
            "market_docs": [], "indices": {}, "macro": {}, "synthesis": None}
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
        macro = _macro_context()                            # 매크로 지표 (D-112)
        if force:                                          # 버튼: 재종합(sonnet, 프롬프트 해시 캐시)
            from pipeline.macro_news import fetch_feeds
            feeds = fetch_feeds()                           # 매체·Fed 헤드라인 (D-206)
            feed_gaps = [f"{f['publisher']} 피드 수집 실패({f['reason']})" for f in feeds["failed"]]
            macro_issues = _macro_issues(conn, lead["trade_date"])
            synthesis = _synthesize(conn, lead["trade_date"], clusters, idio, movers,
                                    discourse, indices, macro, macro_issues, feed_gaps)
        else:                                              # 로드: 저장된 종합 읽기(LLM 없음)
            synthesis = _read_synthesis(conn, lead["trade_date"])
    finally:
        conn.close()

    base.update({"clusters": clusters, "idiosyncratic": idio, "movers": movers,
                 "market_themes": discourse["themes"], "market_docs": discourse["docs"],
                 "indices": indices, "macro": macro, "synthesis": synthesis})
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
                "market_docs": [], "indices": {}, "macro": {}, "synthesis": synthesis}
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

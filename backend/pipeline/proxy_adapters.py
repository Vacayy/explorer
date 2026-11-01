"""프록시 보드 어댑터 (D-240, docs/specs/question-proxy.md '프록시 보드') — LLM 0, 네트워크 0.

지표 하나 = 참조 문자열 `kind:body`. 어댑터는 원천 테이블을 그 자리에서 읽는다(proxy_observations에 복사하지 않음).
값 계산은 각 원천의 기존 함수를 재사용한다(회사채 스프레드·수출입 파생지표·개인 투자 백분위·섹터 RS·Risk 정본).

| kind | ref | 값 | 변화 기준 |
|---|---|---|---|
| credit | `credit:ORCL` · `credit:group:hyperscaler` | 회사채 스프레드(bp), 묶음은 구성사 평균 | 30일 전 |
| trade | `trade:854232` · `trade:854232:yoy` · `trade:2825202000:import:yoy` | 월 수출액(USD) 또는 mom·yoy·yoy3m(%)·z(z_yoy) | 전월 |
| call_momentum | `call_momentum:guidance_raised_count` · `call_momentum:NVDA` | 실적 시즌별 기업 수, 티커면 발표별 모멘텀 점수 | 직전 시즌 같은 경과 시점(티커는 직전 발표) |
| indicator | `indicator:risk_hy` · `indicator:risk_curve` · `indicator:macro_dxy` | market_indicators 값(risk_*는 정본 정제·bp 환산) | 30일 전 |
| retail | `retail:forced_20` · `retail:forced_20_pct` | 개인 투자 파생지표, `_pct`는 5년 백분위 | 30일 전 |
| sector | `sector:반도체·전자부품` · `sector:반도체·전자부품:rs_long` | 대분류 단기 RS(기본)·장기 RS 백분위 | 3주 전(궤적) |
| price | `price:005930` | 종가(원) | 30일 전 |
| tw | `tw:2330` · `tw:2330:yoy3m` · `tw:layer:server:yoy3m` | 대만 월매출(억 TWD)·YoY·3개월 YoY(%), 층 합계 | 전월 |
| transcript | `transcript:<proxy_id>` | 컨콜 추출 수치(태세는 방향 +1/0/−1) | 직전 관측 |
| corpus | `corpus:<proxy_id>` | 문서 여론 방향 +1/0/−1 | 직전 관측 |

공통 계약: `catalog(conn, q, limit)` → [{ref, label, unit}] · `describe(conn, ref)` → {ref, label, unit} | None(원천 없음)
· `series(conn, ref, since)` → [(date, value)] · `latest(conn, ref)` → {value, as_of(원천 날짜), change, change_basis, unit, ...}.
날짜는 원천 날짜 그대로다(수출입은 'YYYY-MM'). as_of는 절대 '지금'이 아니다.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

LATEST_SPAN_DAYS = 800          # latest 계산에 읽는 기간 — 월간·시즌 지표도 직전 기준점이 들어오게
_TTL = 300
_memo: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, fn: Callable[[], object]):
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    value = fn()
    _memo[key] = (time.time(), value)
    return value


def _match(q: str | None, *texts) -> bool:
    """부분 일치(대소문자 무시). 3자 이하 영문 토큰은 단어 경계로만 — 'AI'가 Airbnb·AIR 쿨러에 걸리지 않게."""
    if not q:
        return True
    if q.isascii() and len(q) <= 3:
        pat = re.compile(rf"(?<![A-Za-z]){re.escape(q)}(?![A-Za-z])", re.I)
        return any(pat.search(t or "") for t in texts)
    q = q.lower()
    return any(q in (t or "").lower() for t in texts)


@dataclass(frozen=True)
class Adapter:
    kind: str
    label: str
    ref_format: str
    description: str
    catalog: Callable[..., list[dict]]
    describe: Callable[[sqlite3.Connection, str], dict | None]       # body → {label, unit} | None
    series: Callable[[sqlite3.Connection, str, str], list[tuple[str, float]]]
    lookback: tuple[str, int]                                        # ('days', 30) | ('points', 1)
    basis: str                                                       # 변화 기준 표시: '30일 전' | '전월' ...
    span_days: int = 92                                              # 보드 상세 기본 시계열 길이
    pct_change: bool = False                                         # 수준 지표 — 변화율(%)도 붙인다
    base_fn: Callable | None = None                                  # (conn, body, pts) → ((date, value), basis) | None — 변화 기준 재정의


# ── credit (회사채 스프레드, D-230) ───────────────────────────────────────────

CREDIT_CARRY_DAYS = 10


def _credit_bonds(conn) -> dict[str, str]:
    from pipeline import credit_spreads as cs
    cs.ensure_schema(conn)
    return {r[0]: r[1] for r in conn.execute("SELECT ticker, maturity FROM credit_bonds") if r[1]}


def _credit_catalog(conn, q=None, limit=50):
    from pipeline import credit_spreads as cs
    bonds = _credit_bonds(conn)
    groups = dict(cs.GROUPS)
    out = []
    for key, label in cs.GROUPS:
        if any(c["group"] == key and c["ticker"] in bonds for c in cs.COMPANIES) and _match(q, key, label, "평균"):
            out.append({"ref": f"credit:group:{key}", "label": f"{label} 평균 회사채 스프레드", "unit": "bp"})
    for c in cs.COMPANIES:
        if c["ticker"] in bonds and _match(q, c["ticker"], c["name"], c["issuer"], groups[c["group"]]):
            out.append({"ref": f"credit:{c['ticker']}", "label": f"{c['name']}({c['ticker']}) 회사채 스프레드", "unit": "bp"})
    return out[:limit]


def _credit_describe(conn, body):
    from pipeline import credit_spreads as cs
    bonds = _credit_bonds(conn)
    if body.startswith("group:"):
        key = body[6:]
        label = dict(cs.GROUPS).get(key)
        if label and any(c["group"] == key and c["ticker"] in bonds for c in cs.COMPANIES):
            return {"label": f"{label} 평균 회사채 스프레드", "unit": "bp"}
        return None
    c = cs.BY_TICKER.get(body)
    if c and body in bonds:
        return {"label": f"{c['name']}({body}) 회사채 스프레드", "unit": "bp"}
    return None


def _credit_series(conn, body, since):
    from pipeline import credit_spreads as cs
    if not body.startswith("group:"):
        return [(p["date"], p["spread_bp"]) for p in cs.spread_series(conn, body, since) if p["spread_bp"] is not None]
    bonds = _credit_bonds(conn)
    members = [c["ticker"] for c in cs.COMPANIES if c["group"] == body[6:] and c["ticker"] in bonds]
    per = [{p["date"]: p["spread_bp"] for p in cs.spread_series(conn, t, since) if p["spread_bp"] is not None} for t in members]
    per = [s for s in per if s]
    if not per:
        return []
    # 회사채는 거래가 드문 종목이 많다(TRACE). 각 구성사의 마지막 값을 최대 CREDIT_CARRY_DAYS일 이어 쓰고,
    # 구성이 바뀌는 날의 평균 점프를 피하려고 구성사 전원이 값을 가진 날만 평균한다
    out, last = [], [None] * len(per)
    for d in sorted(set().union(*per)):
        cutoff = (date.fromisoformat(d) - timedelta(days=CREDIT_CARRY_DAYS)).isoformat()
        for i, s in enumerate(per):
            if d in s:
                last[i] = (d, s[d])
        if all(x and x[0] >= cutoff for x in last):
            out.append((d, round(sum(x[1] for x in last) / len(last), 1)))
    return out


# ── trade (수출입, D-140) ────────────────────────────────────────────────────

TRADE_METRICS = {"value": ("", "USD"), "mom": (" 전월비", "%"), "yoy": (" YoY", "%"), "yoy3m": (" 3개월 YoY", "%"), "z": (" YoY z", "z")}


def _trade_parse(body: str) -> tuple[str, str, str] | None:
    parts = body.split(":")
    hs, flow, metric = parts[0], "export", "value"
    for p in parts[1:]:
        if p in ("export", "import"):
            flow = p
        elif p in TRADE_METRICS:
            metric = p
        else:
            return None
    return (hs, flow, metric) if hs else None


def _trade_label(name: str, flow: str, metric: str) -> str:
    return f"{name} {'수입' if flow == 'import' else '수출'}{TRADE_METRICS[metric][0]}"


def _trade_catalog(conn, q=None, limit=50):
    rows = conn.execute("SELECT tf.hs_code, tf.item_name, tf.group_label FROM trade_follow tf "
                        "WHERE tf.active=1 AND EXISTS (SELECT 1 FROM trade_stats ts WHERE ts.hs_code=tf.hs_code) "
                        "ORDER BY tf.rowid").fetchall()   # 등록 순 — 기본 팔로우(메모리·시스템반도체…)가 앞
    out = []
    for r in rows:
        if not _match(q, r["hs_code"], r["item_name"], r["group_label"]):
            continue
        flow = "import" if "수입" in (r["item_name"] or "") else "export"
        pre = f"trade:{r['hs_code']}" + (":import" if flow == "import" else "")
        out.append({"ref": pre, "label": _trade_label(r["item_name"], flow, "value"), "unit": "USD"})
        out.append({"ref": f"{pre}:yoy", "label": _trade_label(r["item_name"], flow, "yoy"), "unit": "%"})
    return out[:limit]


def _trade_describe(conn, body):
    parsed = _trade_parse(body)
    if not parsed:
        return None
    hs, flow, metric = parsed
    r = conn.execute("SELECT item_name FROM trade_follow WHERE hs_code=?", (hs,)).fetchone()
    if not r or not conn.execute("SELECT 1 FROM trade_stats WHERE hs_code=? LIMIT 1", (hs,)).fetchone():
        return None
    return {"label": _trade_label(r["item_name"], flow, metric), "unit": TRADE_METRICS[metric][1]}


def _trade_series(conn, body, since):
    from pipeline import trade_metrics as tm
    parsed = _trade_parse(body)
    if not parsed:
        return []
    hs, flow, metric = parsed
    out = []
    for p in tm.derive(tm.raw_series(conn, hs), flow):
        v = p.get("z_yoy") if metric == "z" else p.get(metric)
        if v is None or p["period"] < since[:7]:
            continue
        out.append((p["period"], round(v * 100, 2) if TRADE_METRICS[metric][1] == "%" else round(v, 2)))
    return out


# ── call_momentum (실적 발언 모멘텀, D-217) ──────────────────────────────────

_CAPEX = re.compile(r"capex|capital expenditure|capital spending|capital investment", re.I)
_AI = re.compile(r"\bai\b|artificial intelligence|gpu|accelerator|data ?cent|inference|\bllm|generative|hbm|hyperscal", re.I)


def _growth_raised(r):
    from pipeline.call_momentum import GROWTH_METRIC
    return any(g.get("direction") == "raised" and GROWTH_METRIC.search(g.get("metric") or "") for g in r["guidance"])


CALL_AGGREGATES: dict[str, tuple[str, Callable[[dict], bool]]] = {
    "guidance_raised_count": ("성장 가이던스 상향 기업 수(시즌)", _growth_raised),
    "capex_raised_count": ("CAPEX 가이던스 상향 기업 수(시즌)",
                           lambda r: any(g.get("direction") == "raised" and _CAPEX.search(g.get("metric") or "") for g in r["guidance"])),
    "new_driver_count": ("새 성장 동인 등장 기업 수(시즌)", lambda r: any(d.get("status") == "new" for d in r["drivers"])),
    "ai_driver_count": ("AI 관련 동인 새로·가속 기업 수(시즌)",
                        lambda r: any(d.get("status") in ("new", "accelerating") and _AI.search(d.get("name") or "") for d in r["drivers"])),
    "candidate_count": ("실적 모멘텀 후보 기업 수(시즌)", lambda r: r["status"] == "candidate"),
}


def _call_rows(conn) -> list[dict]:
    out = []
    for r in conn.execute("SELECT ticker, event_date, score, status, reasons FROM call_momentum ORDER BY event_date"):
        try:
            reasons = json.loads(r["reasons"] or "{}")
        except ValueError:
            reasons = {}
        out.append({"ticker": r["ticker"], "event_date": r["event_date"], "score": r["score"], "status": r["status"],
                    "drivers": reasons.get("drivers") or [], "guidance": reasons.get("guidance") or []})
    return out


def _call_catalog(conn, q=None, limit=50):
    out = [{"ref": f"call_momentum:{k}", "label": label, "unit": "개"} for k, (label, _) in CALL_AGGREGATES.items() if _match(q, k, label)]
    for r in conn.execute("SELECT cm.ticker, max(tf.company_name) name FROM call_momentum cm "
                          "LEFT JOIN transcript_follow tf ON tf.ticker=cm.ticker GROUP BY cm.ticker ORDER BY cm.ticker"):
        if _match(q, r["ticker"], r["name"]):
            out.append({"ref": f"call_momentum:{r['ticker']}", "label": f"{r['name'] or r['ticker']}({r['ticker']}) 실적 모멘텀 점수", "unit": "점"})
    return out[:limit]


def _call_describe(conn, body):
    if body in CALL_AGGREGATES:
        return {"label": CALL_AGGREGATES[body][0], "unit": "개"} if conn.execute("SELECT 1 FROM call_momentum LIMIT 1").fetchone() else None
    r = conn.execute("SELECT max(tf.company_name) name, count(*) n FROM call_momentum cm "
                     "LEFT JOIN transcript_follow tf ON tf.ticker=cm.ticker WHERE cm.ticker=?", (body,)).fetchone()
    return {"label": f"{r['name'] or body}({body}) 실적 모멘텀 점수", "unit": "점"} if r and r["n"] else None


def _call_series(conn, body, since):
    from pipeline.call_momentum import season
    rows = _call_rows(conn)
    if body not in CALL_AGGREGATES:
        # 첫 발표('first')는 비교 대상이 없어 점수가 0으로 고정 — 계열에서 뺀다
        return [(r["event_date"], r["score"]) for r in rows if r["ticker"] == body and r["status"] != "first" and r["event_date"] >= since]
    pred = CALL_AGGREGATES[body][1]
    seasons: dict[str, dict] = {}
    for r in rows:
        s = seasons.setdefault(season(r["event_date"])["key"], {"last": r["event_date"], "hit": set()})
        s["last"] = max(s["last"], r["event_date"])
        if pred(r):
            s["hit"].add(r["ticker"])
    # 점 날짜 = 그 시즌 마지막 발표일(원천 날짜). 진행 중인 시즌은 지금까지 발표한 기업만 센다
    return [(s["last"], float(len(s["hit"]))) for _, s in sorted(seasons.items()) if s["last"] >= since]


def _call_base(conn, body, pts):
    """진행 중인 시즌의 집계를 직전 시즌 전체와 비교하면 시즌 초마다 '급감'으로 보인다.
    직전 시즌의 같은 경과 시점(시즌 시작 + 현재 시즌 마지막 발표까지의 일수)까지 센 값과 비교한다."""
    from pipeline.call_momentum import season
    if body not in CALL_AGGREGATES or not pts:
        return None
    cur = season(pts[-1][0])
    cur_start = date.fromisoformat(cur["start"])
    elapsed = (date.fromisoformat(pts[-1][0]) - cur_start).days
    prev_day = (cur_start - timedelta(days=1)).isoformat()
    prev = season(prev_day)
    prev_cut = (date.fromisoformat(prev["start"]) + timedelta(days=elapsed)).isoformat()
    pred = CALL_AGGREGATES[body][1]
    hit = {r["ticker"] for r in _call_rows(conn) if prev["start"] <= r["event_date"] <= min(prev_cut, prev_day) and pred(r)}
    return (prev_cut, float(len(hit))), f"직전 시즌 같은 시점({elapsed}일차)"


# ── indicator (market_indicators — 매크로·리스크·지수) ──────────────────────

_SUPERSEDED = {"vix", "fear_greed", "macro_us2y", "macro_us10y"}   # 정본 risk_* 가 있는 레거시 계열(pipeline/indicator_canon.py)


def _indicator_meta(key: str) -> dict:
    from pipeline import macro, risk
    from pipeline.indices import INDICES
    if key == "risk_curve":
        return {"label": "미 국채 10Y − 2Y", "unit": "bp"}
    if key.startswith("risk_") and key[5:] in risk.META:
        m = risk.META[key[5:]]
        return {"label": m["label"], "unit": m["unit"]}
    if key.startswith("macro_"):
        m = next((i for i in macro.INDICATORS if i["key"] == key[6:]), None)
        if m:
            return {"label": m["label"], "unit": {"pct": "%", "usd": "USD"}.get(m["fmt"])}
    if key.startswith("index_"):
        m = next((i for i in INDICES if i[0] == key[6:]), None)
        if m:
            return {"label": m[1], "unit": "pt"}
    return {"label": key, "unit": None}


def _indicator_keys(conn) -> list[str]:
    keys = [r[0] for r in conn.execute("SELECT DISTINCT indicator FROM market_indicators WHERE value IS NOT NULL ORDER BY indicator")
            if not r[0].startswith("risk_sync_") and r[0] not in _SUPERSEDED]
    if "risk_us10y" in keys and "risk_us2y" in keys:
        keys.append("risk_curve")
    return keys


def _indicator_catalog(conn, q=None, limit=50):
    out = []
    for k in _indicator_keys(conn):
        m = _indicator_meta(k)
        if _match(q, k, m["label"]):
            out.append({"ref": f"indicator:{k}", **m})
    return out[:limit]


def _indicator_describe(conn, body):
    if body == "risk_curve":
        ok = all(conn.execute("SELECT 1 FROM market_indicators WHERE indicator=? AND value IS NOT NULL LIMIT 1", (k,)).fetchone()
                 for k in ("risk_us10y", "risk_us2y"))
        return _indicator_meta(body) if ok else None
    if body.startswith("risk_sync_") or body in _SUPERSEDED:
        return None
    if not conn.execute("SELECT 1 FROM market_indicators WHERE indicator=? AND value IS NOT NULL LIMIT 1", (body,)).fetchone():
        return None
    return _indicator_meta(body)


def _indicator_raw(conn, key, since):
    from pipeline import macro, risk
    rows = conn.execute("SELECT snapshot_date, value FROM market_indicators WHERE indicator=? AND snapshot_date>=? "
                        "AND value IS NOT NULL ORDER BY snapshot_date", (key, since)).fetchall()
    pairs = [(r[0], r[1]) for r in rows]
    if key.startswith("risk_") and key[5:] in risk.META:
        k = key[5:]
        scale = 100 if risk.META[k]["unit"] == "bp" else 1          # risk.get_risk와 같은 환산
        return [(d, round(v * scale, 4)) for d, v in risk.clean_rows(k, pairs, date.today())]
    if key.startswith("macro_"):
        m = next((i for i in macro.INDICATORS if i["key"] == key[6:]), {})
        return [(d, round(v * m.get("scale", 1), 4)) for d, v in pairs]
    return pairs


def _indicator_series(conn, body, since):
    if body == "risk_curve":   # risk.get_risk의 curve와 같은 계산: (10Y − 2Y) × 100bp, 두 계열이 모두 있는 날만
        ten, two = dict(_indicator_raw(conn, "risk_us10y", since)), dict(_indicator_raw(conn, "risk_us2y", since))
        return [(d, round((ten[d] - two[d]) * 100, 4)) for d in sorted(ten.keys() & two.keys())]
    return _indicator_raw(conn, body, since)


# ── retail (개인 투자 열기, D-231) ───────────────────────────────────────────

def _retail_meta() -> dict[str, dict]:
    from pipeline.retail_heat import METRICS
    out = {}
    for key, label, unit in METRICS:
        out[key] = {"label": label, "unit": {"rate": "%", "ratio": "%", "krw": "KRW"}[unit], "scale": 100 if unit in ("rate", "ratio") else 1}
        out[f"{key}_pct"] = {"label": f"{label} 5년 백분위", "unit": "백분위", "scale": 1}
    return out


def _retail_points(conn) -> list[dict]:
    from pipeline import retail_heat
    retail_heat.ensure_schema(conn)
    stamp = tuple(conn.execute("SELECT max(date), count(*) FROM retail_flows").fetchone())
    return _cached(("retail", stamp), lambda: retail_heat.computed(conn))


def _retail_catalog(conn, q=None, limit=50):
    if not _retail_points(conn):
        return []
    return [{"ref": f"retail:{k}", "label": m["label"], "unit": m["unit"]} for k, m in _retail_meta().items() if _match(q, k, m["label"])][:limit]


def _retail_describe(conn, body):
    m = _retail_meta().get(body)
    if not m or not any(p.get(body) is not None for p in _retail_points(conn)):
        return None
    return {"label": m["label"], "unit": m["unit"]}


def _retail_series(conn, body, since):
    m = _retail_meta().get(body)
    if not m:
        return []
    return [(p["date"], round(p[body] * m["scale"], 4)) for p in _retail_points(conn) if p["date"] >= since and p.get(body) is not None]


# ── sector (섹터 RS 사분면) ──────────────────────────────────────────────────

def _sector_parse(body: str) -> tuple[str, str]:
    name, _, metric = body.partition(":")
    return name, metric or "rs_short"


def _sector_catalog(conn, q=None, limit=50):
    out = []
    for r in conn.execute("SELECT DISTINCT group_name FROM sector_map ORDER BY group_name"):
        if _match(q, r[0], "섹터", "rs"):
            out.append({"ref": f"sector:{r[0]}", "label": f"{r[0]} 단기 RS(1M)", "unit": "백분위"})
            out.append({"ref": f"sector:{r[0]}:rs_long", "label": f"{r[0]} 장기 RS(12M)", "unit": "백분위"})
    return out[:limit]


def _sector_describe(conn, body):
    name, metric = _sector_parse(body)
    if metric not in ("rs_short", "rs_long") or not conn.execute("SELECT 1 FROM sector_map WHERE group_name=? LIMIT 1", (name,)).fetchone():
        return None
    return {"label": f"{name} {'단기 RS(1M)' if metric == 'rs_short' else '장기 RS(12M)'}", "unit": "백분위"}


def _sector_series(conn, body, since):
    """섹터 맵과 같은 계산(sector_rs.compute_sector_map, 15분 캐시)의 현재 + 1·2·3주 전 궤적.
    compute_sector_map은 자기 연결을 연다 — conn은 쓰지 않는다."""
    from pipeline import sector_rs
    name, metric = _sector_parse(body)
    m = sector_rs.compute_sector_map()
    g = next((x for x in m.get("groups", []) if x["name"] == name), None)
    if not g or not m.get("as_of"):
        return []
    d = date.fromisoformat(m["as_of"])
    pts = [((d - timedelta(weeks=t["weeks_ago"])).isoformat(), t[metric]) for t in reversed(g["trail"])]
    pts.append((m["as_of"], g[metric]))
    return [(day, float(v)) for day, v in pts if v is not None]


# ── price (국내 종목 종가) ───────────────────────────────────────────────────

def _price_catalog(conn, q=None, limit=50):
    sql = ("SELECT c.stock_code, c.corp_name FROM companies c WHERE c.stock_code IS NOT NULL AND c.stock_code != '' "
           "AND EXISTS (SELECT 1 FROM stock_prices sp WHERE sp.stock_code=c.stock_code)")
    params: list = []
    if q:
        sql += " AND (c.corp_name LIKE ? OR c.stock_code LIKE ?)"
        params += [f"%{q}%", f"{q}%"]
    rows = conn.execute(sql + " ORDER BY c.stock_code LIMIT ?", (*params, limit)).fetchall()
    return [{"ref": f"price:{r['stock_code']}", "label": f"{r['corp_name']} 주가", "unit": "원"} for r in rows]


def _price_describe(conn, body):
    if not conn.execute("SELECT 1 FROM stock_prices WHERE stock_code=? AND close IS NOT NULL LIMIT 1", (body,)).fetchone():
        return None
    r = conn.execute("SELECT corp_name FROM companies WHERE stock_code=? LIMIT 1", (body,)).fetchone()
    return {"label": f"{r['corp_name'] if r else body} 주가", "unit": "원"}


def _price_series(conn, body, since):
    return [(r[0], float(r[1])) for r in conn.execute(
        "SELECT trade_date, close FROM stock_prices WHERE stock_code=? AND trade_date>=? AND close IS NOT NULL ORDER BY trade_date",
        (body, since))]


# ── tw (대만 월매출, docs/specs/tw-revenue.md) ──────────────────────────────

_TW_METRICS = {None: ("월매출", "억 TWD"), "yoy": ("월매출 YoY", "%"), "yoy3m": ("월매출 3개월 YoY", "%")}


def _tw_parse(body: str) -> tuple[list[str], str, str | None] | None:
    """'2330' · '2330:yoy3m' · 'layer:server:yoy3m' → (회사 코드들, 이름, 지표)"""
    from pipeline.tw_universe import COMPANIES, LAYERS
    parts = body.split(":")
    if parts[0] == "layer" and len(parts) >= 2:
        label = dict(LAYERS).get(parts[1])
        codes = [c for c, _, l, _ in COMPANIES if l == parts[1]]
        metric = parts[2] if len(parts) > 2 else None
        return (codes, f"대만 {label} 합계", metric) if label and metric in _TW_METRICS else None
    name = next((n for c, n, *_ in COMPANIES if c == parts[0]), None)
    metric = parts[1] if len(parts) > 1 else None
    return ([parts[0]], f"대만 {name}", metric) if name and metric in _TW_METRICS else None


def _tw_catalog(conn, q=None, limit=50):
    from pipeline.tw_universe import COMPANIES, LAYERS
    out = []
    for key, label in LAYERS:
        if _match(q, label, "대만", "layer"):
            out += [{"ref": f"tw:layer:{key}:yoy3m", "label": f"대만 {label} 합계 월매출 3개월 YoY", "unit": "%"}]
    for code, name, _, role in COMPANIES:
        if _match(q, name, code, role, "대만"):
            out += [{"ref": f"tw:{code}:yoy3m", "label": f"대만 {name} 월매출 3개월 YoY", "unit": "%"},
                    {"ref": f"tw:{code}", "label": f"대만 {name} 월매출", "unit": "억 TWD"}]
    return out[:limit]


def _tw_describe(conn, body):
    p = _tw_parse(body)
    if not p or not conn.execute("SELECT 1 FROM tw_monthly_revenue WHERE code=? LIMIT 1", (p[0][0],)).fetchone():
        return None
    title, unit = _TW_METRICS[p[2]]
    return {"label": f"{p[1]} {title}", "unit": unit}


def _tw_series(conn, body, since):
    p = _tw_parse(body)
    if not p:
        return []
    codes, _, metric = p
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue WHERE code IN "
                        f"({','.join('?' * len(codes))}) GROUP BY ym ORDER BY ym", codes).fetchall()
    months = [(r["ym"], r["r"], r["ly"]) for r in rows if r["n"] == len(codes)]
    out = []
    for i, (ym, rev, ly) in enumerate(months):
        if metric is None:
            v = rev / 100_000                                   # 천 TWD → 억 TWD
        elif metric == "yoy":
            v = (rev / ly - 1) * 100 if ly else None
        else:
            win = months[max(0, i - 2):i + 1]
            v = (sum(m[1] for m in win) / sum(m[2] for m in win) - 1) * 100 if len(win) == 3 and all(m[2] for m in win) else None
        if v is not None and ym >= since[:7]:
            out.append((ym, round(v, 2)))
    return out


# ── transcript · corpus (기존 프록시 관측, proxy_observations) ──────────────

_DIR = {"up": 1.0, "flat": 0.0, "down": -1.0}


def _obs_modalities(kind: str) -> tuple[str, ...]:
    return ("sentiment",) if kind == "corpus" else ("numeric", "stance")


def _obs_proxy(conn, kind, body):
    if not body.isdigit():
        return None
    mods = _obs_modalities(kind)
    return conn.execute(f"SELECT id, label, unit, modality FROM proxy_registry WHERE id=? AND COALESCE(modality,'numeric') IN "
                        f"({','.join('?' * len(mods))})", (int(body), *mods)).fetchone()


def _obs_catalog_for(kind):
    def catalog(conn, q=None, limit=50):
        mods = _obs_modalities(kind)
        rows = conn.execute(
            f"SELECT pr.id, pr.label, pr.unit, pr.modality FROM proxy_registry pr WHERE pr.active=1 AND COALESCE(pr.modality,'numeric') IN "
            f"({','.join('?' * len(mods))}) AND EXISTS (SELECT 1 FROM proxy_observations po WHERE po.proxy_id=pr.id AND "
            f"(po.value_num IS NOT NULL OR (COALESCE(pr.modality,'numeric')!='numeric' AND po.direction IN ('up','down','flat')))) "
            f"ORDER BY pr.id", mods).fetchall()   # 값이 하나라도 있는 프록시만
        return [{"ref": f"{kind}:{r['id']}", "label": r["label"], "unit": _obs_unit(r)} for r in rows if _match(q, r["label"])][:limit]
    return catalog


def _obs_unit(p) -> str | None:
    return p["unit"] if (p["modality"] or "numeric") == "numeric" else "방향"


def _obs_describe_for(kind):
    def describe(conn, body):
        p = _obs_proxy(conn, kind, body)
        return {"label": p["label"], "unit": _obs_unit(p)} if p else None
    return describe


def _obs_series_for(kind):
    def series(conn, body, since):
        p = _obs_proxy(conn, kind, body)
        if not p:
            return []
        numeric = (p["modality"] or "numeric") == "numeric"
        out = []
        for r in conn.execute("SELECT observed_at, value_num, direction FROM proxy_observations WHERE proxy_id=? AND observed_at>=? "
                              "ORDER BY observed_at, id", (p["id"], since)):
            v = r["value_num"] if numeric else _DIR.get(r["direction"])
            if v is not None:
                out.append((r["observed_at"][:10], float(v)))
        return out
    return series


# ── 레지스트리 ──────────────────────────────────────────────────────────────

ADAPTERS: dict[str, Adapter] = {a.kind: a for a in [
    Adapter("credit", "회사채 스프레드", "credit:<티커> | credit:group:<묶음키>",
            "AI 설비투자 기업 회사채의 국채 대비 스프레드(bp). 묶음은 구성사 평균", _credit_catalog, _credit_describe, _credit_series, ("days", 30), "30일 전"),
    Adapter("trade", "수출입", "trade:<HS>[:import][:mom|yoy|yoy3m|z]",
            "관세청 월별 수출입. 기본은 수출액(USD), 접미사로 증가율(%)·YoY z", _trade_catalog, _trade_describe, _trade_series,
            ("points", 1), "전월", span_days=400, pct_change=True),
    Adapter("call_momentum", "컨콜 모멘텀", "call_momentum:<집계키> | call_momentum:<티커>",
            "실적 발표 추출(call_momentum)에서 시즌별 기업 수 집계, 또는 티커별 모멘텀 점수", _call_catalog, _call_describe, _call_series,
            ("points", 1), "직전 발표", span_days=730, base_fn=_call_base),
    Adapter("indicator", "매크로·리스크", "indicator:<market_indicators 키> | indicator:risk_curve",
            "금리·신용 스프레드·VIX·환율·지수 등. risk_* 는 정본 계열", _indicator_catalog, _indicator_describe, _indicator_series, ("days", 30), "30일 전"),
    Adapter("retail", "개인 투자", "retail:<지표키>[_pct]",
            "개인 신용융자·예탁금·반대매매 등 20일 파생지표와 5년 백분위", _retail_catalog, _retail_describe, _retail_series, ("days", 30), "30일 전"),
    Adapter("sector", "섹터 RS", "sector:<대분류>[:rs_long]",
            "대분류 시총가중 수익률의 백분위(단기 1M 기본, 장기 12M). 현재와 1·2·3주 전 궤적", _sector_catalog, _sector_describe, _sector_series,
            ("points", 3), "3주 전", span_days=30),
    Adapter("tw", "대만 월매출", "tw:<코드>[:yoy|yoy3m] | tw:layer:<층>[:yoy|yoy3m]",
            "대만 92개사 월매출(억 TWD)·YoY·3개월 YoY, 층 합계도 가능", _tw_catalog, _tw_describe, _tw_series,
            ("points", 1), "전월", span_days=730),
    Adapter("price", "가격", "price:<종목코드>", "국내 종목 일별 종가(원)", _price_catalog, _price_describe, _price_series, ("days", 30), "30일 전",
            pct_change=True),
    Adapter("transcript", "컨콜 추출(기존)", "transcript:<proxy_id>", "기존 질문 프록시의 컨콜 추출 수치·태세",
            _obs_catalog_for("transcript"), _obs_describe_for("transcript"), _obs_series_for("transcript"), ("points", 1), "직전 관측", span_days=730),
    Adapter("corpus", "문서 여론(기존)", "corpus:<proxy_id>", "기존 질문 프록시의 문서 여론 방향(+1/0/−1)",
            _obs_catalog_for("corpus"), _obs_describe_for("corpus"), _obs_series_for("corpus"), ("points", 1), "직전 관측", span_days=730),
]}


def parse(ref: str | None, kind: str | None = None) -> tuple[str, str] | None:
    """'credit:ORCL' → ('credit', 'ORCL'). kind를 주면 접두사 없는 ref도 받는다. 모르는 kind면 None."""
    ref = (ref or "").strip()
    if kind and ref.partition(":")[0] in ADAPTERS and not ref.startswith(f"{kind}:"):
        return None                                  # 다른 어댑터의 ref
    if kind and not ref.startswith(f"{kind}:"):
        ref = f"{kind}:{ref}"
    k, sep, body = ref.partition(":")
    if not sep or k not in ADAPTERS or not body or (kind and k != kind):
        return None
    return k, body


def describe(conn, ref: str, kind: str | None = None) -> dict | None:
    """원천에 실제로 있는 ref면 {ref, adapter, label, unit}, 아니면 None."""
    p = parse(ref, kind)
    if not p:
        return None
    meta = ADAPTERS[p[0]].describe(conn, p[1])
    return {"ref": f"{p[0]}:{p[1]}", "adapter": p[0], **meta} if meta else None


def catalog(conn, kind: str, q: str | None = None, limit: int = 50) -> list[dict]:
    return ADAPTERS[kind].catalog(conn, q=q, limit=limit)


def series(conn, ref: str, since: str) -> list[tuple[str, float]]:
    p = parse(ref)
    return ADAPTERS[p[0]].series(conn, p[1], since) if p else []


def _base(adapter: Adapter, pts: list[tuple[str, float]]) -> tuple[str, float] | None:
    unit, n = adapter.lookback
    last = pts[-1]
    if unit == "points":
        return pts[-1 - n] if len(pts) > n else None
    cutoff = (date.fromisoformat(last[0][:10]) - timedelta(days=n)).isoformat()
    older = [p for p in pts if p[0] <= cutoff]
    return older[-1] if older else None


def snapshot(conn, ref: str, days: int | None = None) -> dict:
    """latest + 시계열 한 번에(원천을 한 번만 읽는다). days=None이면 어댑터 기본 길이."""
    p = parse(ref)
    if not p:
        return {"latest": empty_latest(None), "series": []}
    adapter = ADAPTERS[p[0]]
    days = days or adapter.span_days
    span = max(days, LATEST_SPAN_DAYS)
    pts = adapter.series(conn, p[1], (date.today() - timedelta(days=span)).isoformat())
    meta = adapter.describe(conn, p[1]) or {}
    cut = (date.today() - timedelta(days=days)).isoformat()
    shown = [pt for pt in pts if pt[0] >= cut[:len(pt[0])]] if pts else []
    return {"latest": _latest(adapter, pts, meta.get("unit"), conn, p[1]), "series": [{"date": d, "value": v} for d, v in shown]}


def empty_latest(unit):
    return {"value": None, "as_of": None, "change": None, "change_pct": None, "change_basis": None, "direction": None, "unit": unit}


def _latest(adapter: Adapter, pts, unit, conn=None, body=None) -> dict:
    if not pts:
        return empty_latest(unit)
    last = pts[-1]
    custom = adapter.base_fn(conn, body, pts) if adapter.base_fn else None
    base, basis = custom if custom else (_base(adapter, pts), adapter.basis)
    change = round(last[1] - base[1], 4) if base else None
    level = adapter.pct_change and unit not in ("%", "z")     # 증가율·z의 변화율은 뜻이 없다
    pct = round(change / abs(base[1]) * 100, 2) if base and level and base[1] else None
    direction = None if change is None else "up" if change > 0 else "down" if change < 0 else "flat"
    return {"value": last[1], "as_of": last[0], "change": change, "change_pct": pct,
            "change_basis": basis if base else None, "direction": direction, "unit": unit}


def latest(conn, ref: str) -> dict:
    return snapshot(conn, ref)["latest"]

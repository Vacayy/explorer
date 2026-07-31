"""매크로·유동성 트래킹 (docs/specs/macro.md) — market_indicators 스냅샷 재사용.

매크로(키 없음, yfinance): 미10Y(^TNX)·달러 DXY·유가(WTI)·금·신용 HYG·비트코인.
유동성(FRED 무료키 FRED_API_KEY): Fed 대차대조표(WALCL)·TGA(WTREGEN)·역레포(RRPONTSYD)·M2(M2SL).
  → **순유동성 = WALCL − TGA − RRP** (= MacroMicro US Liquidity Index, 읽을 때 계산).
FRED 키 없으면 유동성 축만 degraded(매크로는 정상).

갱신은 버튼 주도(D-100 계승): GET=스냅샷 순수 읽기, POST /snapshot=재수집. 지표는 market_indicators에
'macro_' 프리픽스로 적재(시장 국면과 네임스페이스 분리).
"""
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from database import get_connection
from pipeline.market_regime import _series, _yf_history

# 키 없음 (yfinance) — 종가 시계열
YF = {"us10y": "^TNX", "dxy": "DX-Y.NYB", "oil": "CL=F", "gold": "GC=F", "hyg": "HYG", "btc": "BTC-USD"}
# FRED (무료키) — 유동성 구성요소
FRED = {"fed_bs": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD", "m2": "M2SL"}
# 단위 → 십억달러($B) 정규화: WALCL·WTREGEN=백만$, RRPONTSYD·M2=십억$
_FRED_TO_B = {"fed_bs": 1 / 1000, "tga": 1 / 1000, "rrp": 1.0, "m2": 1.0}

# 표시 메타 (label·group·fmt) — group: rates|liquidity|credit|commodity
INDICATORS = [
    {"key": "us10y", "label": "미 10Y 금리", "group": "rates", "fmt": "pct"},
    {"key": "dxy", "label": "달러 DXY", "group": "rates", "fmt": "num"},
    {"key": "net_liq", "label": "순유동성", "group": "liquidity", "fmt": "trillion_b"},
    {"key": "m2", "label": "M2", "group": "liquidity", "fmt": "trillion_b"},
    {"key": "hyg", "label": "HYG(신용)", "group": "credit", "fmt": "num"},
    {"key": "btc", "label": "비트코인", "group": "credit", "fmt": "usd"},
    {"key": "oil", "label": "유가 WTI", "group": "commodity", "fmt": "usd"},
    {"key": "gold", "label": "금", "group": "commodity", "fmt": "usd"},
]
GROUP_LABEL = {"rates": "금리·달러", "liquidity": "유동성", "credit": "신용·위험선호", "commodity": "원자재"}


def _fred_history(series_id: str, days: int = 400) -> list[tuple[str, float]]:
    """FRED observations → [(date, value)]. 키 없으면 빈 리스트(유동성 degraded)."""
    key = os.getenv("FRED_API_KEY")
    if not key:
        return []
    start = (date.today() - timedelta(days=days)).isoformat()
    q = urllib.parse.urlencode({"series_id": series_id, "api_key": key,
                                "file_type": "json", "observation_start": start})
    req = urllib.request.Request(f"https://api.stlouisfed.org/fred/series/observations?{q}",
                                 headers={"User-Agent": "stock-explorer"})
    with urllib.request.urlopen(req, timeout=15) as r:
        obs = json.loads(r.read().decode()).get("observations", [])
    return [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (None, ".", "")]


# ── 적재 (버튼/크론) ─────────────────────────────────────────────────────────

def snapshot_macro() -> dict:
    """매크로·유동성 전 지표 fetch → market_indicators('macro_*') 멱등 적재. 실패는 개별 흡수."""
    fetched: dict[str, list] = {}
    degraded: list[str] = []

    def _try(name, fn):
        try:
            rows = fn()
            if rows:
                fetched[name] = rows
            else:
                degraded.append(name)
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{name}({type(e).__name__})")

    for name, ticker in YF.items():
        _try(name, lambda t=ticker: _yf_history(t))
    for name, sid in FRED.items():
        _try(name, lambda s=sid: _fred_history(s))

    conn = get_connection()
    n = 0
    for indicator, rows in fetched.items():
        for d, v in rows:
            conn.execute("INSERT OR REPLACE INTO market_indicators(snapshot_date, indicator, value) "
                         "VALUES (?,?,?)", (d, f"macro_{indicator}", round(v, 4)))
            n += 1
    conn.commit()
    conn.close()
    _refresh_signal()   # 신호등 산문 생성(sonnet, signature 캐시) — 버튼/스냅샷 때만
    return {"rows": n, "indicators": list(fetched), "degraded": degraded}


# ── 읽기 (일반 로드 — 순수, 네트워크 없음) ────────────────────────────────────

def _net_liquidity_series(raw: dict) -> list[tuple[str, float]]:
    """순유동성($B) = WALCL − TGA − RRP. 혼합 주기 → 날짜 정렬 + forward-fill 후 차감."""
    if not (raw.get("fed_bs") and raw.get("tga") and raw.get("rrp")):
        return []
    import pandas as pd
    def s(name):
        return pd.Series({d: v * _FRED_TO_B[name] for d, v in raw[name]})
    df = pd.concat([s("fed_bs").rename("bs"), s("tga").rename("tga"), s("rrp").rename("rrp")],
                   axis=1).sort_index().ffill().dropna()
    net = df["bs"] - df["tga"] - df["rrp"]
    return [(str(i), round(float(v), 2)) for i, v in net.items()]


def _change_pct(series: list[tuple[str, float]], back: int = 5) -> float | None:
    """최근값 대비 back기 전 대비 변화율(%). 시계열 짧으면 None."""
    if len(series) < back + 1:
        return None
    prev = series[-1 - back][1]
    if not prev:
        return None
    return round((series[-1][1] - prev) / abs(prev) * 100, 2)


def _interpret(items: list[dict]) -> dict:
    """지표 → 위험자산 배경 해석 (결정적 frame · LLM 0 · 정답 아님, 지표=fact/해석=frame 계승 D-076).

    핵심축: 순유동성 방향(위험자산과 최밀착) + 금리·달러(완화/긴축) + 신용(HYG). 점수 합으로 우호/혼조/역풍.
    """
    by = {it["key"]: it for it in items}
    def chg(k):
        it = by.get(k)
        return it["change_pct"] if it and it["change_pct"] is not None else None

    score, notes = 0, []
    nl = chg("net_liq")
    if nl is not None:
        if nl > 0.5:
            score += 1; notes.append(f"순유동성 개선(+{nl}%)")
        elif nl < -0.5:
            score -= 1; notes.append(f"순유동성 위축({nl}%)")
    y, dx = chg("us10y"), chg("dxy")
    if y is not None and dx is not None and y < -0.3 and dx < -0.3:
        score += 1; notes.append("금리·달러 동반 하락(완화적)")
    elif y is not None and dx is not None and y > 0.3 and dx > 0.3:
        score -= 1; notes.append("금리·달러 동반 상승(긴축적)")
    elif dx is not None and dx < -0.5:
        notes.append("달러 약세(위험선호 우호)")
    elif dx is not None and dx > 0.5:
        notes.append("달러 강세(위험자산 부담)")
    hyg = chg("hyg")
    if hyg is not None and hyg > 0.3:
        score += 1; notes.append("신용 우호(HYG↑)")
    elif hyg is not None and hyg < -0.3:
        score -= 1; notes.append("신용 경계(HYG↓)")

    stance = "우호" if score >= 1 else "역풍" if score <= -1 else "혼조"
    if not notes:
        return {"stance": "혼조", "comment": "지표 변화가 크지 않아 배경은 중립적입니다."}
    return {"stance": stance, "comment": " · ".join(notes) + f" → 위험자산 배경 {stance}"}


# ── 신호등 산문 해설 (sonnet, 스냅샷 때 생성·캐시 — D-102) ────────────────────

def _signal_signature(items: list[dict]) -> str:
    basis = "|".join(f"{it['key']}:{it['value']}:{round(it['change_pct'] or 0, 2)}" for it in items)
    return hashlib.sha256(basis.encode()).hexdigest()


def _signal_prompt(items: list[dict], interp: dict) -> str:
    lines = "\n".join(
        f"- [{it['group_label']}] {it['label']}: {it['value']} "
        f"({'+' if (it['change_pct'] or 0) > 0 else ''}{it['change_pct']}%)" for it in items)
    return (
        "당신은 아침 매크로 전략가다. 아래는 전날 미국장 마감 기준 매크로·유동성 지표다. "
        "투자자에게 **신호등** 역할을 하는 해설을 써라 — 단순 서술이 아니라, 이 배경에서 위험자산에 "
        "실어도 되는지(green)·선별하며 경계인지(yellow)·방어인지(red)를 판단해 준다.\n\n"
        f"[지표]\n{lines}\n\n"
        f"[결정적 참고 — 규칙 기반 초안]\n{interp['stance']}: {interp['comment']}\n\n"
        "핵심 관점: 순유동성(Fed BS−TGA−RRP)이 위험자산과 가장 밀착 — 방향이 실탄이다. "
        "금리·달러 하락=완화적(우호)·상승=긴축적(부담), 신용스프레드(HYG)=위험선호 온도, "
        "원자재(유가·금)=인플레·안전자산 쏠림. 여러 축이 엇갈리면 솔직히 yellow로. "
        "주어진 숫자에 근거해서만 말하고 없는 사건은 지어내지 마라.\n"
        "JSON만 출력: {\"signal\": \"green|yellow|red\", "
        "\"headline\": \"신호등의 뜻을 한 줄로(예: '유동성 뒷심 약화 — 선별적 접근')\", "
        "\"comment\": \"3~4문장. ①왜 이 신호인지 지표 근거 ②투자자에게 무엇을 의미하는지(비중·방어·헤지 등 포지셔닝 함의) "
        "③지금 가장 주시해야 할 지표 하나와 그 트리거\"}"
    )


def _refresh_signal() -> None:
    """스냅샷 직후 신호등 산문 생성(sonnet). signature 불변이면 재사용, 엔진 미가용이면 건너뜀."""
    from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
    data = get_macro(with_signal=False)
    items = data["items"]
    if not items or not data["as_of"]:
        return
    sig = _signal_signature(items)
    conn = get_connection()
    row = conn.execute("SELECT signature FROM macro_signals WHERE as_of=?", (data["as_of"],)).fetchone()
    if (row and row["signature"] == sig) or llm_engine() != "claude-code":
        conn.close()
        return
    try:
        r = _parse_json(_call_claude_code(_signal_prompt(items, _interpret(items)), model="sonnet", timeout=180))
    except Exception:
        conn.close()
        return
    conn.execute(
        "INSERT OR REPLACE INTO macro_signals(as_of, signature, signal, headline, comment, model, created_at) "
        "VALUES (?,?,?,?,?, 'sonnet', datetime('now'))",
        (data["as_of"], sig, r.get("signal"), r.get("headline"), r.get("comment")))
    conn.commit()
    conn.close()


def _read_signal(as_of: str | None) -> dict | None:
    if not as_of:
        return None
    conn = get_connection()
    row = conn.execute("SELECT signal, headline, comment FROM macro_signals WHERE as_of=?", (as_of,)).fetchone()
    conn.close()
    if not row or not row["comment"]:
        return None
    return {"signal": row["signal"], "headline": row["headline"], "comment": row["comment"]}


def get_macro(with_signal: bool = True) -> dict:
    """매크로·유동성 지표 그룹 + 스파크라인 + 신호등 산문. LLM 0(읽기). market_indicators 순수 읽기."""
    conn = get_connection()
    raw = {name: _series(conn, f"macro_{name}") for name in [*YF, *FRED]}
    conn.close()

    series_of = dict(raw)
    series_of["net_liq"] = _net_liquidity_series(raw)   # 파생 (십억$)

    items, degraded = [], []
    for meta in INDICATORS:
        k = meta["key"]
        ser = series_of.get(k) or []
        if not ser:
            degraded.append(meta["label"])
            continue
        value = ser[-1][1]
        if meta["fmt"] == "trillion_b":   # $B → $T 표시용
            value = round(value / 1000, 2)
            ser = [(d, round(v / 1000, 3)) for d, v in ser]
        items.append({
            "key": k, "label": meta["label"], "group": meta["group"], "group_label": GROUP_LABEL[meta["group"]],
            "fmt": meta["fmt"], "value": value, "change_pct": _change_pct(ser),
            "series": [v for _, v in ser][-40:],
        })

    as_of = max((s[-1][0] for s in series_of.values() if s), default=None)
    return {"as_of": as_of, "items": items, "degraded": degraded,
            "interpretation": _interpret(items) if items else None,   # 결정적 폴백/LLM 입력
            "signal": _read_signal(as_of) if with_signal else None,    # 신호등 산문(sonnet)
            "fred_enabled": bool(os.getenv("FRED_API_KEY"))}

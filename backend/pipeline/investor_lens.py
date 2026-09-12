"""투자 렌즈 — 가치/추세 관점의 종목 판단 (docs/specs/investor-lens.md).

투자관을 원칙 원장(vault/principles/{value,trend}.md)에 사람이 촘촘히 쌓고, 렌즈는 그 원칙
전문을 **압축 없이 통째 주입**해 종목 재료 위에서 "이 관점이라면 이 종목을 어떻게 읽는가"를
종합한다. 판정 오라클이 아니라 프레임(hypothesis) — 근거는 그래프·펀더·프록시로 역추적.

- 생성 시점: 열람 시 게으르게. principles_hash+material_hash가 바뀐 경우에만 LLM 호출
- 종목별·렌즈별 in-flight 락(LLM 중복 호출 방지), LLM 호출은 트랜잭션 밖 (stock_brief 패턴)
- append-only 히스토리 (판단 변화 추적, D-047 철학)
- 1차 구현: **가치 렌즈(value)**. 추세 렌즈(trend)·4상한은 후속(스펙 구현순서 3~4)
"""
import hashlib
import json
import os
import subprocess
import threading

from config import VAULT_PATH
from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

# 종합=sonnet — 브리프·기술 재료가 이미 정제돼 있어 opus 불요 (스펙 결정)
LENS_MODEL = os.getenv("LENS_MODEL", "sonnet")
PRINCIPLES_DIR = VAULT_PATH / "principles"
LENS_TYPES = ("value", "trend")


def load_principles(lens_type: str) -> tuple[str | None, str]:
    """원칙 원장 전문 + 해시(16자). 파일 없으면 (None, '')."""
    path = PRINCIPLES_DIR / f"{lens_type}.md"
    if not path.exists():
        return None, ""
    text = path.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode()).hexdigest()[:16]


def _call_json_lens(prompt: str) -> dict:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--setting-sources", "", "--tools", "", "--model", LENS_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lens_lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# ── 가치 렌즈 재료 (원칙 3: 현금의 질 / 원칙 2: 구조적 동인·해자) ────────────────

_OCF_NAMES = {"영업활동현금흐름", "영업활동으로인한현금흐름"}
_ICF_NAMES = {"투자활동현금흐름", "투자활동으로인한현금흐름"}
_CAPEX_NAMES = {"유형자산의취득", "유형자산취득", "유형자산의증가"}


def _cf_quality(conn, corp_code: str | None, net_income: int | None) -> dict | None:
    """현금의 질 (원칙 3) — 최근 연간 영업/투자활동현금흐름·CAPEX·FCF·이익의 질(OCF/순이익).

    account_nm 변형은 공백 제거 후 매칭, CFS 우선 OFS fallback. 값 없으면 None(Partial 허용).
    """
    if not corp_code:
        return None
    from services.dart_service import _parse_amount
    rows = conn.execute("""
        SELECT fs_div, account_nm, thstrm_amount FROM financial_statements
        WHERE corp_code=? AND reprt_code='11011' AND sj_div='CF'
          AND bsns_year=(SELECT max(bsns_year) FROM financial_statements
                         WHERE corp_code=? AND reprt_code='11011' AND sj_div='CF')""",
        (corp_code, corp_code)).fetchall()
    if not rows:
        return None
    ocf = icf = capex = None
    for fs_pref in ("CFS", "OFS"):
        sub = [r for r in rows if r["fs_div"] == fs_pref]
        if not sub:
            continue
        for r in sub:
            key = (r["account_nm"] or "").replace(" ", "")
            amt = _parse_amount(r["thstrm_amount"])
            if key in _OCF_NAMES and ocf is None:
                ocf = amt
            elif key in _ICF_NAMES and icf is None:
                icf = amt
            elif key in _CAPEX_NAMES and capex is None:
                capex = amt
        if ocf is not None:
            break
    if ocf is None:
        return None
    fcf = (ocf - abs(capex)) if capex is not None else None
    quality = round(ocf / net_income, 2) if (net_income and net_income > 0) else None
    return {"ocf": ocf, "icf": icf, "capex": capex, "fcf": fcf, "earnings_quality": quality}


def _causal_edges(conn, entity_id: int) -> list[dict]:
    """이 종목을 둘러싼 인과 엣지 (원칙 2 — 미래 확신의 구조적 동인·해자).

    hypothesis 인과 엣지 중 이 엔티티가 원인/결과로 걸린 것, 확신 순 top 8.
    """
    rows = conn.execute("""
        SELECT r.rel_type, r.mechanism, r.confidence, r.effect_direction,
               r.reference_period, s.name AS src_name, d.name AS dst_name,
               r.src_id, r.dst_id
        FROM entity_relations r
        JOIN entities s ON s.id = r.src_id
        JOIN entities d ON d.id = r.dst_id
        WHERE r.epistemic_type='hypothesis' AND r.rel_type IN ('CAUSES','BENEFITS_FROM')
          AND (r.src_id=? OR r.dst_id=?)
        ORDER BY r.confidence DESC LIMIT 8""", (entity_id, entity_id)).fetchall()
    return [dict(r) for r in rows]


def gather_material(conn, code: str, entity_id: int, lens_type: str, market: str = "kr") -> dict:
    """렌즈 재료 취합 (LLM 0). market=kr(재무제표·컨센서스) | us(yfinance). 재사용 우선(스펙 원칙 4)."""
    if lens_type == "trend":
        m = _gather_trend(conn, code, market)
        m["market"] = market
        return m
    if lens_type != "value":
        return {}
    m = _gather_value_us(conn, code, entity_id) if market == "us" else _gather_value_kr(conn, code, entity_id)
    m["market"] = market
    return m


def _gather_value_kr(conn, stock_code: str, entity_id: int) -> dict:
    from pipeline.stock_brief import gather_inputs
    from pipeline.upside_model import _anchor
    base = gather_inputs(conn, stock_code, entity_id)
    anchor = _anchor(conn, stock_code)
    try:
        from pipeline.report import _cached_upside
        upside = _cached_upside(conn, anchor.get("name"))
    except Exception:
        upside = {}
    return {
        "anchor": anchor,
        "consensus": base.get("consensus"),
        "decomp": base.get("decomp"),
        "per_band": base.get("per_band"),
        "sentiment": base.get("sentiment"),
        "knowledge": base.get("knowledge"),
        "cf": _cf_quality(conn, anchor.get("corp_code"), anchor.get("net_income")),
        "edges": _causal_edges(conn, entity_id),
        "upside": upside or {},
    }


def _gather_value_us(conn, ticker: str, entity_id: int) -> dict:
    """US 가치 재료 — yfinance(밸류·EPS 개정·현금의 질) + 인과엣지 + 최근 컨콜 정리."""
    from pipeline.us_data import get_fundamentals
    fund = get_fundamentals(ticker)
    edges = _causal_edges(conn, entity_id) if entity_id else []
    row = conn.execute("""
        SELECT digest FROM transcripts WHERE ticker=? AND digest IS NOT NULL
        ORDER BY call_date DESC LIMIT 1""", (ticker.upper(),)).fetchone()
    return {"fundamentals": fund, "edges": edges, "transcript_digest": row["digest"] if row else None}


def _has_material(m: dict, lens_type: str = "value") -> bool:
    if lens_type == "trend":
        return bool(m.get("technicals"))
    if m.get("market") == "us":
        return bool(m.get("fundamentals"))
    a = m.get("anchor") or {}
    return bool(a.get("revenue") or a.get("net_income") or m.get("consensus") or m.get("cf"))


def material_hash(m: dict, principles_hash: str, lens_type: str = "value") -> str:
    """느리게 변하는 재료만 지문에 — 매일 바뀌는 주가로 재생성되지 않게(비용 게이트).

    추세는 원자 가격이 아니라 '질적 추세 상태'(부호·존·버킷)로 지문 → 상태가 바뀔 때만 재생성.
    """
    if lens_type == "trend":
        return hashlib.sha256(f"pr:{principles_hash}|{_trend_signature(m)}".encode()).hexdigest()
    if m.get("market") == "us":
        f = m.get("fundamentals") or {}
        est = f.get("estimates") or {}
        us_parts = [f"pr:{principles_hash}",
                    f"us:{f.get('fwd_pe')}:{f.get('fwd_eps')}:{f.get('fcf')}:{f.get('earnings_quality')}",
                    f"rev:{(est.get('revisions') or {}).get('+1y')}"]
        for e in m.get("edges") or []:
            us_parts.append(f"ed:{e['src_id']}:{e['dst_id']}:{e['confidence']}")
        return hashlib.sha256("|".join(str(p) for p in us_parts).encode()).hexdigest()
    a = m.get("anchor") or {}
    parts = [f"pr:{principles_hash}",
             f"anc:{a.get('eps')}:{a.get('revenue')}:{a.get('net_income')}"]
    for c in m.get("consensus") or []:
        parts.append(f"cs:{c['fiscal_year']}:{c['fwd_eps']}:{c['target_price']}")
    cf = m.get("cf") or {}
    parts.append(f"cf:{cf.get('ocf')}:{cf.get('fcf')}:{cf.get('earnings_quality')}")
    for e in m.get("edges") or []:
        parts.append(f"ed:{e['src_id']}:{e['dst_id']}:{e['rel_type']}:{e['confidence']}")
    for k in m.get("knowledge") or []:
        parts.append(f"kn:{k['id']}:{k.get('independent_n')}")
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _fmt(v, unit=""):
    if v is None:
        return "미상"
    if isinstance(v, (int, float)) and abs(v) >= 1e8:
        return f"{v/1e8:,.0f}억{unit}"
    return f"{v:,}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"


def _material_blocks(m: dict) -> str:
    if m.get("market") == "us":
        return _value_blocks_us(m)
    a = m.get("anchor") or {}
    blocks = [
        "[현재 밸류·실적 앵커]\n"
        f"- 현재가 {_fmt(a.get('price'), '원')} · PER {_fmt(a.get('per'), '배')} · EPS {_fmt(a.get('eps'))}\n"
        f"- 최근 연간 매출 {_fmt(a.get('revenue'), '원')} · 당기순이익 {_fmt(a.get('net_income'), '원')}"
        f" · 순이익률 {_fmt(a.get('net_margin'), '%')}"
    ]
    cs = m.get("consensus") or []
    lines = [f"- {c['fiscal_year'][:4]}E: Fwd EPS {c['fwd_eps']:,.0f}원 · Fwd PER {c['fwd_per']}배"
             + (f" · 목표주가 {c['target_price']:,.0f}원" if c["target_price"] else "")
             for c in cs if c["fwd_eps"]]
    if lines:
        blocks.append("[컨센서스 — 시장이 보는 미래(Forward)]\n" + "\n".join(lines))
    cf = m.get("cf")
    if cf:
        q = cf.get("earnings_quality")
        blocks.append(
            "[현금의 질 — 최근 연간]\n"
            f"- 영업활동현금흐름 {_fmt(cf.get('ocf'), '원')}"
            + (f" · 투자활동현금흐름 {_fmt(cf.get('icf'), '원')}" if cf.get("icf") is not None else "")
            + (f" · CAPEX {_fmt(cf.get('capex'), '원')}" if cf.get("capex") is not None else "")
            + (f" · FCF {_fmt(cf.get('fcf'), '원')}" if cf.get("fcf") is not None else "")
            + (f"\n- 이익의 질(영업CF/순이익) {q}배 — 1 미만이면 회계이익 대비 현금전환이 약함" if q is not None else ""))
    edges = m.get("edges") or []
    if edges:
        el = []
        for e in edges:
            arrow = "→" if e["rel_type"] == "CAUSES" else "←수혜"
            dirn = {"positive": "(+)", "negative": "(−)", "mixed": "(±)"}.get(e.get("effect_direction"), "")
            el.append(f"- {e['src_name']} {arrow} {e['dst_name']} {dirn}"
                      + (f": {e['mechanism']}" if e.get("mechanism") else "")
                      + (f" [확신 {e['confidence']:.2f}]" if e.get("confidence") else ""))
        blocks.append("[인과 그래프 — 이 종목을 둘러싼 구조적 동인·해자 (원칙 2)]\n" + "\n".join(el))
    if m.get("decomp"):
        d = m["decomp"]
        blocks.append(f"[상승 분해 (근사 — {d['year']}년 실적)]\n"
                      f"12개월 주가 {d['price_chg_12m']:+}% = 순이익 YoY {d['earnings_chg_yoy']:+}% × 멀티플 {d['multiple_chg']:+}%")
    up = m.get("upside") or {}
    if up:
        blocks.append("[캐시된 업사이드 모델 (있으면 상방·하방 참고)]\n" + json.dumps(up, ensure_ascii=False)[:600])
    if m.get("knowledge"):
        from pipeline.knowledge_recall import knowledge_block
        blocks.append(knowledge_block(
            m["knowledge"], "승격된 지식 — 이 종목에 대해 시스템이 반복·독립 관측으로 검증한 전제").strip())
    return "\n\n".join(blocks)


def _num(v):
    return "미상" if v is None else (f"{v:,.1f}" if isinstance(v, float) else f"{v:,}")


def _usd_big(v):
    if v is None:
        return "미상"
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:,.1f}B"
    if a >= 1e6:
        return f"{v/1e6:,.0f}M"
    return f"{v:,.0f}"


def _value_blocks_us(m: dict) -> str:
    """US 가치 재료 블록 — yfinance(밸류·개정 방향·현금의 질) + 인과엣지 + 컨콜 정리."""
    f = m.get("fundamentals") or {}
    est = f.get("estimates") or {}
    blocks = []
    pt = est.get("price_targets") or {}
    up = round((pt["mean"] - f["price"]) / f["price"] * 100, 1) if (pt.get("mean") and f.get("price")) else None
    blocks.append(
        "[현재 밸류 — Forward 우선]\n"
        f"- 현재가 ${_num(f.get('price'))} · 시총 ${_usd_big(f.get('market_cap'))}\n"
        f"- Fwd PER {_num(f.get('fwd_pe'))}배 · trailing PER {_num(f.get('trailing_pe'))}배 · Fwd EPS ${_num(f.get('fwd_eps'))}"
        + (f"\n- 애널리스트 목표가 평균 ${_num(pt.get('mean'))} (${_num(pt.get('low'))}~${_num(pt.get('high'))})"
           + (f" · 현재가 대비 {up:+}%" if up is not None else "") if pt else ""))
    rev = (est.get("revisions") or {}).get("+1y") or (est.get("revisions") or {}).get("0y")
    et = est.get("eps_trend_1y") or {}
    e1 = est.get("earnings_1y") or {}
    rl = []
    if rev:
        rl.append(f"차년 EPS 상향 {rev.get('up30')}건 vs 하향 {rev.get('down30')}건 (최근 30일) — 개정 방향")
    if et.get("current") and et.get("d90"):
        d = (et["current"] - et["d90"]) / abs(et["d90"]) * 100 if et["d90"] else 0
        rl.append(f"차년 EPS 추정 90일 변화 {d:+.1f}% (현재 ${_num(et['current'])} vs 90일전 ${_num(et['d90'])})")
    if e1.get("growth") is not None:
        rl.append(f"차년 이익 성장 컨센 {e1['growth']*100:+.0f}% (애널리스트 {e1.get('analysts')}명)")
    if rl:
        blocks.append("[컨센서스·개정 방향 — 시장이 보는 미래(Forward)]\n" + "\n".join("- " + x for x in rl))
    q = f.get("earnings_quality")
    if f.get("ocf") is not None or f.get("fcf") is not None:
        blocks.append(
            "[현금의 질 — 최근 연간]\n"
            f"- 영업현금흐름 ${_usd_big(f.get('ocf'))} · CAPEX ${_usd_big(f.get('capex'))} · FCF ${_usd_big(f.get('fcf'))}\n"
            f"- 매출 ${_usd_big(f.get('revenue'))} · 순이익 ${_usd_big(f.get('net_income'))}"
            + (f"\n- 이익의 질(영업CF/순이익) {q}배 — 1 미만이면 회계이익 대비 현금전환이 약함" if q is not None else ""))
    edges = m.get("edges") or []
    if edges:
        el = []
        for e in edges:
            arrow = "→" if e["rel_type"] == "CAUSES" else "←수혜"
            dirn = {"positive": "(+)", "negative": "(−)", "mixed": "(±)"}.get(e.get("effect_direction"), "")
            el.append(f"- {e['src_name']} {arrow} {e['dst_name']} {dirn}"
                      + (f": {e['mechanism']}" if e.get("mechanism") else "")
                      + (f" [확신 {e['confidence']:.2f}]" if e.get("confidence") else ""))
        blocks.append("[인과 그래프 — 구조적 동인·해자 (원칙 2)]\n" + "\n".join(el))
    if m.get("transcript_digest"):
        blocks.append("[최근 컨콜 핵심 정리 — 경영진 1차 발언(미래 확신 근거)]\n" + m["transcript_digest"][:1200])
    return "\n\n".join(blocks) or "(재료 부족)"


def _build_value_prompt(name: str, principles_text: str, m: dict) -> str:
    from pipeline.digests import STYLE_RULES
    return (
        f"너는 아래 '가치 렌즈 원칙 원장'을 체화한 투자자다. 이 원칙 전문에 비춰 '{name}' 종목을 읽어라. "
        "재료 나열이 아니라 원칙에 근거한 판단이다.\n\n"
        "규율:\n"
        "- 너는 판정 오라클이 아니다. '매수/매도'가 아니라 '이 원칙에서 이 종목이 어떻게 읽히는가'를 쓴다.\n"
        "- 모든 판단은 아래 재료의 구체 근거를 인용한다. 재료에 없는 사실을 창작하지 않는다.\n"
        "- 미래 이익·현금흐름 극대화 확신의 '설득력'이 핵심이다. 과거 장부는 그 확신의 검증 준거일 뿐.\n"
        "- 밸류 상한은 거부권이다 — 미래를 다 감안해도 이미 그 이상 반영됐으면 확신을 낮춘다.\n"
        "- 근거가 부족한 축은 정직하게 '판단 유보'라고 쓴다.\n\n"
        "=== 가치 렌즈 원칙 원장 (전문) ===\n" + principles_text.strip() + "\n=== 원장 끝 ===\n\n"
        "[재료]\n" + _material_blocks(m) + "\n\n"
        + STYLE_RULES +
        'JSON만 출력: {'
        '"body": "마크다운 판독. 구조: 첫 문단 종합 2~3문장 + '
        '### 미래 확신(설득력) / ### 구조적 동인·해자 / ### 현금의 질 / ### 밸류 상한 / '
        '### 상방·하방 비대칭 / ### 무엇이 이 확신을 틀리게 하나 (재료 없으면 그 섹션 생략)", '
        '"stance": "강|중|약 중 하나 — 미래 이익·현금흐름 극대화 확신의 강도", '
        '"signals": ["역추적용 근거 3~6개 — 인용한 재료를 짧게(예: 이익의 질 1.3배, CUDA 락인 엣지)"]}'
    )


# ── 추세 렌즈 재료·프롬프트 (원칙: 시장 수용·위치 맥락·대응 규율) ────────────────

def _gather_trend(conn, code: str, market: str = "kr") -> dict:
    from pipeline.technicals import compute_technicals, volume_by_price
    table = "us_prices" if market == "us" else "stock_prices"
    if market == "us":
        from pipeline.us_data import BENCHMARK, fetch_prices
        fetch_prices(code)          # 캐시 신선하면 no-op
        fetch_prices(BENCHMARK)
    tech = compute_technicals(conn, code, table=table)
    vp = volume_by_price(conn, code, table=table)
    if market == "us":
        rel = _us_rel_strength(conn, code)
        rs, rs_bucket = rel, _us_rs_bucket(rel)
    else:
        rs = _rs_short_for(conn, code)
        rs_bucket = _rs_bucket(rs)
    try:
        from pipeline.market_regime import get_regime
        regime = (get_regime() or {}).get("us" if market == "us" else "kr") or {}
    except Exception:
        regime = {}
    return {"technicals": tech, "volume_profile": vp, "rs": rs,
            "rs_bucket": rs_bucket, "regime": regime}


def _us_rel_strength(conn, ticker: str):
    """지수(SPY) 대비 3개월 초과수익(%p) — US 상대강도(KR 유니버스 백분위 대체)."""
    from pipeline.us_data import BENCHMARK

    def ret63(code):
        rows = conn.execute(
            "SELECT close FROM us_prices WHERE stock_code=? ORDER BY trade_date DESC LIMIT 64",
            (code,)).fetchall()
        if len(rows) < 40 or not rows[-1]["close"]:
            return None
        return (rows[0]["close"] - rows[-1]["close"]) / rows[-1]["close"] * 100

    s, b = ret63(ticker.upper()), ret63(BENCHMARK)
    return round(s - b, 1) if (s is not None and b is not None) else None


def _us_rs_bucket(rel) -> str:
    if rel is None:
        return "?"
    return "out+" if rel >= 10 else "in" if rel >= -10 else "out-"


def _rs_short_for(conn, stock_code: str):
    """단기 RS 백분위 (research_candidates 재사용). 전종목 계산 후 해당 종목만."""
    from pipeline.research_candidates import _rs_short
    row = conn.execute("SELECT max(trade_date) d FROM stock_prices").fetchone()
    if not row or not row["d"]:
        return None
    try:
        allrs = _rs_short(conn, row["d"])
    except Exception:
        return None
    v = allrs.get(stock_code)
    return round(v, 1) if v is not None else None


def _rs_bucket(rs) -> str:
    if rs is None:
        return "?"
    return "90+" if rs >= 90 else "70+" if rs >= 70 else "50+" if rs >= 50 else "<50"


def _trend_signature(m: dict) -> str:
    """질적 추세 상태 지문 — 부호·존·버킷만(원자 가격 아님). 상태 전환 시에만 재생성."""
    t = m.get("technicals") or {}

    def sg(x):
        return "?" if x is None else ("+" if x >= 0 else "-")

    def zn(r):
        return "?" if r is None else ("hi" if r >= 70 else "lo" if r <= 30 else "mid")

    def b52(x):
        return "?" if x is None else ("H" if x >= -5 else "M" if x >= -20 else "L")

    reg = m.get("regime") or {}
    vp = m.get("volume_profile") or {}
    poc = "?"
    if vp.get("overhead_pct") is not None:
        poc = "over" if vp["overhead_pct"] > 55 else "under" if vp["overhead_pct"] < 45 else "mid"
    return "|".join([
        f"ma{sg(t.get('ma20_gap'))}{sg(t.get('ma60_gap'))}{sg(t.get('ma120_gap'))}",
        f"rsi{zn(t.get('rsi14'))}", f"h52{b52(t.get('off_52w_high'))}",
        f"reg{reg.get('posture')}:{(reg.get('trend') or {}).get('dir')}",
        f"vp{poc}", f"rs{m.get('rs_bucket')}",
    ])


def _trend_material_blocks(m: dict) -> str:
    us = m.get("market") == "us"
    cur, won = ("$", "") if us else ("", "원")
    blocks = []
    t = m.get("technicals") or {}
    parts = []
    if t.get("rsi14") is not None:
        parts.append(f"RSI14 {t['rsi14']}")
    for k, l in (("ma20_gap", "20일선"), ("ma60_gap", "60일선"), ("ma120_gap", "120일선")):
        if t.get(k) is not None:
            parts.append(f"{l} 대비 {t[k]:+}%")
    if t.get("off_52w_high") is not None:
        parts.append(f"52주 고점 대비 {t['off_52w_high']:+}%")
    if t.get("ret_1m") is not None:
        parts.append(f"1개월 {t['ret_1m']:+}% · 3개월 {t.get('ret_3m')}%")
    if parts:
        blocks.append("[기술적 위치 — 이평·RSI·52주]\n" + " · ".join(parts))
    if m.get("rs") is not None:
        if us:
            blocks.append(f"[상대강도 — 지수(SPY) 대비]\n최근 3개월 초과수익 {m['rs']:+.1f}%p (양수=시장 상회)")
        else:
            blocks.append(f"[상대강도 RS]\n단기(30일 수익률) 전종목 백분위 {m['rs']} (100=최강, 시장 대비 관심 유입)")
    vp = m.get("volume_profile")
    if vp:
        nd = " · ".join(f"{cur}{n['price']:,}{won}({n['vol_pct']}%)" for n in vp["nodes"])
        blocks.append(
            "[매물대 — 최근 거래 가격대별 물량]\n"
            f"현재가 {cur}{vp['cur']:,}{won} · POC(최대 매물) {cur}{vp['poc']:,}{won}"
            f"({'머리 위' if vp['poc_vs_cur']=='above' else '아래'})\n"
            f"현재가 위 저항 물량 {vp['overhead_pct']}% / 아래 지지 물량 {vp['support_pct']}% · "
            f"주요 매물대 {nd} (범위 {cur}{vp['lo']:,}~{cur}{vp['hi']:,}{won}, {vp['window']}일)")
    reg = m.get("regime") or {}
    if reg:
        osc = reg.get("oscillator") or {}
        tr = reg.get("trend") or {}
        vol = reg.get("volatility") or {}
        blocks.append(
            f"[시장 국면({'미국' if us else '국장'}) — 국면 게이트(원칙 7)]\n"
            f"포스처 {reg.get('posture')} · {reg.get('reason')}\n"
            f"{osc.get('metric')} {osc.get('value')}({osc.get('zone')}) · "
            f"20EMA {tr.get('ema')}({tr.get('dir')}) · {vol.get('metric')} {vol.get('value')}({vol.get('band')})")
    return "\n\n".join(blocks) or "(기술 재료 부족)"


def _build_trend_prompt(name: str, principles_text: str, m: dict) -> str:
    from pipeline.digests import STYLE_RULES
    return (
        f"너는 아래 '추세 렌즈 원칙 원장'을 체화한 트레이더다. 이 원칙 전문에 비춰 '{name}'의 추세를 읽어라.\n\n"
        "규율:\n"
        "- 예측하지 않는다(원칙 1). 가격과 추세를 사실로 받아들이고 '위치'와 '대응'을 말한다.\n"
        "- 초입·소외인지 성숙·어깨인지 억지로 단정하지 않는다(원칙 3) — 근거를 늘어놓고, 애매하면 애매하다고 한다.\n"
        "- 추세 훼손 조건(=손절 라인)을 반드시 명시한다(원칙 4). 진입 근거 앵커링·물타기를 경계한다(원칙 2·5).\n"
        "- 모든 판단은 아래 재료의 구체 근거를 인용한다.\n\n"
        "=== 추세 렌즈 원칙 원장 (전문) ===\n" + principles_text.strip() + "\n=== 원장 끝 ===\n\n"
        "[재료]\n" + _trend_material_blocks(m) + "\n\n"
        + STYLE_RULES +
        'JSON만 출력: {'
        '"body": "마크다운 판독. 구조: 첫 문단 종합 2~3문장 + '
        '### 추세 구조(다우 국면·이평·볼밴) / ### 매물대(위 저항·아래 지지) / ### 국면 게이트 / '
        '### 추세 훼손 조건(손절 라인) / ### 대응 규율", '
        '"stance": "초입|진행|성숙|훼손|불명확 중 하나 — 추세 위치(단정 어려우면 불명확)", '
        '"signals": ["역추적용 근거 3~6개"]}'
    )


def compute_quadrant(value_stance: str | None, trend_stance: str | None) -> dict | None:
    """4상한 위치 (LLM 0) — 가치 확신 × 추세 위치. knowledge_state 4상한 재사용(D-090)."""
    if not value_stance or not trend_stance or trend_stance == "불명확":
        return None
    strong = value_stance in ("강", "중")
    early = trend_stance in ("초입", "진행")
    broken = trend_stance == "훼손"
    if strong and early:
        cell, note = "기회", "펀더 확신 + 시장 아직 초입 — 소외된 확신"
    elif strong and not early:
        cell = "늦은 진입"
        note = "추세 훼손 — 되돌림·손절 규율 우선" if broken else "좋은 회사지만 추세 성숙 — 매물대·되돌림 부담, 대응 규율 우선"
    elif not strong and not early:
        cell, note = "과열 경고", "확신 약한데 추세만 성숙 — 모멘텀·투기 과열(진자 경고)"
    else:
        cell, note = "회피", "확신·추세 모두 약함 — 노이즈"
    return {"value_axis": value_stance, "trend_axis": trend_stance, "cell": cell, "note": note}


# ── 실행 ────────────────────────────────────────────────────────────────────

def _get_cached(conn, code: str, lens_type: str, market: str = "kr"):
    return conn.execute(
        "SELECT body, stance, signals_json, principles_hash, material_hash, created_at "
        "FROM lens_readings WHERE stock_code=? AND lens_type=? AND market=? ORDER BY id DESC LIMIT 1",
        (code, lens_type, market)).fetchone()


def _row(r) -> dict:
    return {"body": r["body"], "stance": r["stance"],
            "signals": json.loads(r["signals_json"]) if r["signals_json"] else [],
            "created_at": r["created_at"]}


def _empty() -> dict:
    return {"body": None, "stance": None, "signals": [], "created_at": None}


def _resolve(conn, code: str, market: str):
    """종목 해소. kr=entities aliases / us=transcript_follow(ticker↔entity, 미팔로우여도 티커로 진행)."""
    if market == "us":
        from pipeline.us_data import resolve_us
        eid, name = resolve_us(conn, code)
        return {"id": eid, "name": name or code.upper()}
    r = conn.execute(
        "SELECT id, name FROM entities WHERE type='company' AND aliases=?", (code,)).fetchone()
    return {"id": r["id"], "name": r["name"]} if r else None


def peek(code: str, lens_type: str, market: str = "kr") -> dict | None:
    """LLM 없이 캐시 + stale 플래그. 엔티티/원칙 없거나 재료 없으면 None(FE 미표시)."""
    conn = get_connection()
    ent = _resolve(conn, code, market)
    if not ent:
        conn.close()
        return None
    principles_text, phash = load_principles(lens_type)
    if not principles_text:
        conn.close()
        return None
    material = gather_material(conn, code, ent["id"], lens_type, market)
    if not _has_material(material, lens_type):
        conn.close()
        return None
    cached = _get_cached(conn, code, lens_type, market)
    mhash = material_hash(material, phash, lens_type)
    conn.close()
    if not cached:
        return {"status": "empty", **_empty(), "stale": True}
    return {"status": "cached", **_row(cached), "stale": cached["material_hash"] != mhash}


def compute_reading(code: str, lens_type: str = "value", market: str = "kr", refresh: bool = False) -> dict:
    with _lens_lock(f"{market}:{code}:{lens_type}"):
        return _compute_locked(code, lens_type, market, refresh)


def _compute_locked(code: str, lens_type: str, market: str, refresh: bool) -> dict:
    if lens_type not in LENS_TYPES:
        return {"status": "unsupported"}
    conn = get_connection()
    ent = _resolve(conn, code, market)
    if not ent:
        conn.close()
        return {"status": "not_found"}
    principles_text, phash = load_principles(lens_type)
    if not principles_text:
        conn.close()
        return {"status": "no_principles"}
    material = gather_material(conn, code, ent["id"], lens_type, market)
    if not _has_material(material, lens_type):
        conn.close()
        return {"status": "empty", **_empty()}
    mhash = material_hash(material, phash, lens_type)
    cached = _get_cached(conn, code, lens_type, market)
    if cached and not refresh and cached["material_hash"] == mhash:
        conn.close()
        return {"status": "cached", **_row(cached)}
    if llm_engine() != "claude-code":
        conn.close()
        return {"status": "unavailable", **(_row(cached) if cached else _empty())}
    if lens_type == "value":
        prompt = _build_value_prompt(ent["name"], principles_text, material)
    elif lens_type == "trend":
        prompt = _build_trend_prompt(ent["name"], principles_text, material)
    else:
        conn.close()
        return {"status": "unsupported"}
    try:
        data = _call_json_lens(prompt)  # LLM 호출 — 쓰기 트랜잭션 밖
    except Exception:
        conn.close()
        return {"status": "failed", **(_row(cached) if cached else _empty())}
    signals = data.get("signals")
    conn.execute("""
        INSERT INTO lens_readings
            (stock_code, market, lens_type, body, stance, signals_json,
             principles_hash, material_hash, model)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, market, lens_type, data.get("body"), data.get("stance"),
         json.dumps(signals, ensure_ascii=False) if signals else None,
         phash, mhash, f"claude-code/{LENS_MODEL}"))
    conn.commit()
    row = _get_cached(conn, code, lens_type, market)
    conn.close()
    return {"status": "fresh", **_row(row)}

"""통합 리포트 엔진 v2 — 다중 에이전트 리서치 (report-v2-agents, D-043).

애널리스트 팀(펀더·기술·수급) → 리서처 debate(Bull vs Bear) → 리드 애널리스트 판정
→ 섹션 작성 → 조립. 연쇄 LLM(오케스트레이션 도구 아님, pipeline 순차 호출).
레이팅은 리드가 맥락 종합으로 부여(기계적 임계 오버라이드 폐기). 상상은 debate로 균형.
검증 산출물(analyst·bull·bear·ratings)은 reports.debate_json에 보존 → 서비스 열람.
"""
import hashlib
import json
import statistics

from pipeline.enrich import _call_claude_code, llm_engine
from pipeline.upside_model import _anchor
from pipeline.research_candidates import _rs_short

TOP_RELATED = 5
TOP_STOCKS = 4      # 종목 재분석 대상 (v2는 콜이 많아 축소)
AUGMENT_CAP = 2
BODY_EXCERPT = 500
SCEN_EXCERPT = 600
RATING_RUBRIC = ("레이팅 어휘: 상승여력 ≥50%인 경우 Strong Buy, ≥15% 인 경우 Buy, 그 이하 Hold. "
                 "추세 훼손·과열·논지 붕괴 등 위험이면 Sell. 단 이는 어휘 가이드일 뿐, "
                 "기계적 임계가 아니다 — 펀더·기술 국면·수급을 확률론적으로 종합해 판단하라. "
                 "특히 펀더가 견고한데 쏠림 해소로 조정받아 RS만 급락한 경우는 Sell이 아니라 "
                 "하방 대비 상방이 열린 국면일 수 있다(맥락으로 판단). "
                 "밸류·멀티플은 **12M Fwd PER과 그 변화 추이(리레이팅/디레이팅)·추정 EPS 개정**으로만 "
                 "판단하라. **후행(trailing) PER은 시장이 참고하지 않는 지표이니 논리에 쓰지 마라.**")

# 두괄식 문단 규칙 — 모든 섹션 공통 (사용자 2026-07-21)
PARA_RULE = ("각 문단은 **두괄식**: 첫 문장에 핵심 메시지를 못 박고, 이어지는 문장들에서 "
             "숫자·논리·맥락으로 그 문장을 뒷받침하라.")

# 규격화된 목차 (report-v2-agents / 목차 규격화) — 리드가 Top-down/Bottom-up만 선택, 섹션은 고정.
SECTION_SPECS = {
    "top_down": [
        ("산업 분석", "세계관→내러티브→주목할 catalyst 또는 최근 발생 event로 새롭게 자극된 성장. "
                      "내러티브 중심으로 서술하되, 각 문단 첫 문장은 내러티브 요지, 이어서 숫자·디테일 근거."),
        ("기업 분석", "경영진 분석(경영진 정보가 인물 node에 있을 경우), 사업 분석(무엇으로 버는가·사업부별 매출 비중/구조)과 재무 분석(성장성·수익성·건전성 — "
                      "불건전하지 않은지). 대상 종목들을 아우르되 핵심 종목 위주."),
        ("투자 포인트", "이 기업의 이익 또는 멀티플이 재평가될 이유 — 위 산업·기업 분석에서 연결되는 논리. "
                        "종목별 레이팅의 근거를 여기서 명확히."),
        ("투자 전략", "매크로 환경 + 밸류에이션 + 기술적 국면(RS·이동평균·볼린저)을 종합한 대응 — "
                      "진입/감시 조건, 하방 제한 vs 상방 여지의 비대칭. 타이밍은 추세추종 렌즈로 별도."),
    ],
    "bottom_up": [
        ("기업 분석", "경영진 분석(경영진 정보가 인물 node에 있을 경우), 사업 분석(무엇을 파는가·사업부 구조)과 재무 분석(성장성·수익성·건전성)."),
        ("시장 분석", "이 기업이 노리는/침투하려는 시장의 특성 — 규모·성장·경쟁 구도와 기업의 침투 전략."),
        ("투자 포인트", "이익 또는 멀티플이 재평가될 이유 — 어떤 사업을 어떤 시장에서 어떤 전략으로 전개하는지 포함. "
                        "종목별 레이팅의 근거."),
        ("투자 전략", "매크로 + 밸류에이션 + 기술적 국면을 종합한 대응 — 진입/감시 조건, 비대칭."),
    ],
}


def _parse_json(raw: str) -> dict:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"JSON 없음: {raw[:80]!r}")
    return json.loads(raw[s:e + 1])


def _latest_narr(conn, topic: str):
    return conn.execute(
        "SELECT id, topic, title, body, version FROM narratives "
        "WHERE topic=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC LIMIT 1",
        (topic,)).fetchone()


def _members_hash(members: list[tuple[str, int]]) -> str:
    return hashlib.sha256("|".join(f"{t}:{v}" for t, v in sorted(members)).encode()).hexdigest()


def _anchor_line(a: dict) -> str:
    # trailing PER은 시장이 참고하지 않는 지표라 의도적으로 제외 — 밸류는 _consensus(선행)로만.
    def v(x, unit=""):
        return f"{x}{unit}" if x is not None else "미상"
    return (f"현재가 {v(a.get('price'))}·매출 {v(a.get('revenue'))}·"
            f"순이익률 {v(a.get('net_margin'), '%')}·시총 {v(a.get('market_cap'))}")


def _consensus(conn, code: str) -> str:
    """선행 컨센서스 + **추이** — 12M Fwd PER의 리레이팅/디레이팅과 추정 EPS 개정.
    trailing PER 대신 '선행 멀티플이 어디로 움직이는가'가 시장이 실제로 보는 신호(사용자 2026-07-22)."""
    # 최신 회계연도 기준 히스토리 (같은 FY라야 Fwd PER 비교 가능)
    rows = conn.execute(
        "SELECT fetched_date, fwd_eps, fwd_per, target_price FROM consensus_estimates "
        "WHERE stock_code=? AND fiscal_year=("
        "  SELECT fiscal_year FROM consensus_estimates WHERE stock_code=? "
        "  ORDER BY fetched_date DESC, fiscal_year LIMIT 1) "
        "ORDER BY fetched_date DESC LIMIT 40", (code, code)).fetchall()
    if not rows or not rows[0]["fwd_per"]:
        return ""
    cur, old = rows[0], rows[-1]
    parts = [f"12M Fwd PER {cur['fwd_per']}배"]
    # Fwd PER 추이 (리레이팅/디레이팅) — 창이 하루뿐이면 생략
    if old is not cur and old["fwd_per"] and abs(cur["fwd_per"] - old["fwd_per"]) / old["fwd_per"] >= 0.03:
        arrow = "▲리레이팅" if cur["fwd_per"] > old["fwd_per"] else "▼디레이팅"
        parts.append(f"추이 {old['fetched_date'][5:]}~{cur['fetched_date'][5:]} "
                     f"{old['fwd_per']}→{cur['fwd_per']}배 {arrow}")
    # 추정 EPS 개정 (상향=업그레이드, 가격과 무관한 순수 기대 변화)
    if old is not cur and old["fwd_eps"] and cur["fwd_eps"] and abs(cur["fwd_eps"] - old["fwd_eps"]) / old["fwd_eps"] >= 0.02:
        parts.append(f"추정EPS {'상향' if cur['fwd_eps'] > old['fwd_eps'] else '하향'}")
    if cur["fwd_eps"]:
        parts.append(f"Fwd EPS {round(cur['fwd_eps']):,}원")
    if cur["target_price"]:
        parts.append(f"컨센서스 목표주가 {round(cur['target_price']):,}원")
    return " · ".join(parts)


def _cached_upside_pct(conn, name: str | None) -> float | None:
    if not name:
        return None
    row = conn.execute(
        "SELECT spec_json FROM models WHERE name LIKE ? ORDER BY updated_at DESC LIMIT 1",
        (f"{name} · %업사이드",)).fetchone()
    if not row or not row["spec_json"]:
        return None
    try:
        scens = json.loads(row["spec_json"]).get("scenarios") or []
        base = next((s for s in scens if "기본" in (s.get("name") or "")), None) or (scens[len(scens) // 2] if scens else None)
        return base.get("upside_pct") if base else None
    except Exception:
        return None


def _signals(conn, code: str, name: str | None) -> dict:
    """콜 재료 — 기술(RS·이동평균·볼린저·52주)·심리(언급 모멘텀)·펀더(캐시 업사이드)."""
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    rs = _rs_short(conn, latest).get(code) if latest else None
    closes = [r["close"] for r in conn.execute(
        "SELECT close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT 250", (code,))]
    cur = closes[0] if closes else None

    def ma(n):
        return round(sum(closes[:n]) / n) if len(closes) >= n else None
    ma20, ma60, ma120 = ma(20), ma(60), ma(120)
    pos52 = None
    if cur is not None and len(closes) >= 2:
        w = closes[:250]
        mn, mx = min(w), max(w)
        if mx > mn:
            pos52 = round((cur - mn) / (mx - mn) * 100)
    pctb = None  # 볼린저 %B (20일, ±2σ): 0=하단·100=상단·>100 상단이탈
    if len(closes) >= 20:
        w = closes[:20]
        mid, sd = sum(w) / 20, statistics.pstdev(w)
        if sd > 0:
            pctb = round((cur - (mid - 2 * sd)) / (4 * sd) * 100)
    m = conn.execute("""
        SELECT SUM(CASE WHEN rd.published_at >= datetime('now','-7 days') THEN 1 ELSE 0 END) recent,
               SUM(CASE WHEN rd.published_at >= datetime('now','-14 days')
                         AND rd.published_at < datetime('now','-7 days') THEN 1 ELSE 0 END) prev
        FROM entity_links el JOIN entities e ON e.id=el.entity_id
        JOIN raw_documents rd ON rd.id=el.doc_id
        WHERE el.link_type='stock' AND e.aliases=?""", (code,)).fetchone()
    return {"rs": int(rs) if rs is not None else None, "pos_52w": pos52,
            "price": cur, "ma20": ma20, "ma60": ma60, "ma120": ma120, "bollinger_pctb": pctb,
            "mentions_7d": m["recent"] or 0, "mentions_prev_7d": m["prev"] or 0,
            "upside_cached": _cached_upside_pct(conn, name)}


def _tech_line(s: dict, sig: dict) -> str:
    def rel(price, m):
        if price is None or m is None:
            return "?"
        return "위" if price >= m else "아래"
    p = sig["price"]
    return (f"현재가 {p}·RS {sig['rs'] if sig['rs'] is not None else '?'}(0~100)·"
            f"52주위치 {sig['pos_52w'] if sig['pos_52w'] is not None else '?'}%·"
            f"20일선 {rel(p, sig['ma20'])}/60일선 {rel(p, sig['ma60'])}/120일선 {rel(p, sig['ma120'])}·"
            f"볼린저%B {sig['bollinger_pctb'] if sig['bollinger_pctb'] is not None else '?'}")


# ── LLM 헬퍼 ──
def _call_text(prompt: str, model: str = "sonnet", timeout: int = 240) -> str:
    try:
        return _call_claude_code(prompt, model=model, timeout=timeout).strip()
    except Exception:
        return ""


def _segments(conn, corp_code: str | None) -> str:
    """사업부별 매출 비중 (사업 분석용, best-effort). 없으면 빈 문자열."""
    if not corp_code:
        return ""
    rows = conn.execute(
        "SELECT segment_name, ratio FROM business_segments WHERE corp_code=? "
        "AND bsns_year=(SELECT max(bsns_year) FROM business_segments WHERE corp_code=?) "
        "AND ratio IS NOT NULL ORDER BY ratio DESC LIMIT 5", (corp_code, corp_code)).fetchall()
    return ", ".join(f"{r['segment_name']} {round(r['ratio'])}%" for r in rows)


def _stock_ctx(stocks: list[dict]) -> str:
    """애널리스트·debate 공용 종목 컨텍스트 (앵커·사업부·시그널·다각도 파급)."""
    out = []
    for s in stocks:
        angles = "; ".join(f"[{a['narrative']}]({a.get('rel') or '수혜'}) {a.get('reason') or ''}" for a in s["angles"])
        seg = f"\n  사업부: {s['segments']}" if s.get("segments") else ""
        fwd = f"\n  선행(컨센서스): {s['consensus']}" if s.get("consensus") else ""
        brief = f"\n  [AI 브리프 종합]\n  {s['brief'][:1500].strip()}" if s.get("brief") else ""
        out.append(f"■ {s['name']}({s['code']})\n  재무: {_anchor_line(s['anchor'])}{fwd}{seg}\n"
                   f"  기술: {_tech_line(s, s['sig'])}\n  심리: 최근7일 언급 {s['sig']['mentions_7d']}건"
                   f"(이전 {s['sig']['mentions_prev_7d']}건)\n  펀더 저장 업사이드: "
                   f"{s['sig']['upside_cached'] if s['sig']['upside_cached'] is not None else '미상'}%\n"
                   f"  내러티브별 파급: {angles}{brief}")
    return "\n".join(out)


def _narr_ctx(narr_material: list[dict]) -> str:
    return "\n\n".join(
        f"### {m['topic']} — {m['title'] or ''}\n{(m['body'] or '')[:BODY_EXCERPT]}"
        + (f"\n[파급] {m['scenario'][:SCEN_EXCERPT]}" if m.get("scenario") else "")
        for m in narr_material)


def _analyst(kind: str, narr_ctx: str, stock_ctx: str) -> str:
    from pipeline.lenses import LENS_INDUSTRY, LENS_PATTERN, LENS_CYCLE
    roles = {
        "fundamental": ("펀더멘털 애널리스트", "각 종목의 실적·밸류·리레이팅 여지를 재무 앵커로 평가. "
                        "매출/이익률/PER 기준 저평가·고평가와 그 근거.", LENS_INDUSTRY),
        "technical": ("기술 애널리스트", "각 종목의 기술적 국면을 판정. RS·이동평균(20/60/120)·볼린저%B·"
                      "52주위치를 임계값이 아니라 **국면**(신고가 돌파·과열·건강한 조정·바닥권 등)으로 해석하라. "
                      "펀더가 견고한데 조정으로 RS만 하락한 경우는 위험이 아니라 기회일 수 있음을 구분하라.", LENS_PATTERN),
        "sentiment": ("수급·심리 애널리스트", "언급 모멘텀·쏠림·과열을 평가. 관심 급증이 기회인지 과열 경고인지 판단.", LENS_CYCLE),
    }
    title, task, lens = roles[kind]
    return _call_text(
        f"너는 {title}다. 아래 산업 자료와 종목 데이터를 보고 {task}\n{lens}\n"
        "종목별로 충분히(각 3~5문장) 근거를 들어 평가하고, 산업 전반 코멘트도 상세히. 밸류·멀티플은 "
        "12M Fwd PER과 그 추이(리레이팅/디레이팅)·추정 EPS 개정으로만 밸류를 논하라(후행 PER 금지). 근거 없는 수치 창작 금지. 평서체(분량 넉넉히).\n\n"
        f"[산업 자료]\n{narr_ctx}\n\n[종목 데이터]\n{stock_ctx}")


def _researcher(side: str, narr_ctx: str, stock_ctx: str, analysts: dict, counter: str = "") -> str:
    stance = ("강세(Bull)", "이 산업·종목이 왜 매력적인지 가장 설득력 있는 강세 논지를 세워라. "
              "업계 리더의 방향성 등 아직 실현 안 된 미래도 근거가 타당하면 확률론적으로 당겨와 논해도 된다"
              ) if side == "bull" else (
              "약세(Bear)", "위 강세 논지에 맞서 가장 설득력 있는 약세·반대 논지를 세워라. 쏠림·기울기 한계·"
              "밸류 부담·구조적 리스크 등. 강세 논리와 정면으로 충돌하는 지점을 명확히 하라.")
    role, task = stance
    return _call_text(
        f"너는 {role} 리서처다. {task}\n"
        "핵심 논지 3~5개를 '- 제목: 근거' 형식으로. 각 논지는 위 자료(내러티브·파급·애널리스트 평가)에 "
        "정박해 근거를 충분히 풀어라(논지당 2~3문장). 밸류는 12M Fwd PER·그 추이로만(후행 PER 금지).\n\n"
        f"[산업 자료]\n{narr_ctx}\n\n[종목 데이터]\n{stock_ctx}\n\n"
        f"[애널리스트 평가]\n펀더: {analysts['fundamental']}\n기술: {analysts['technical']}\n수급: {analysts['sentiment']}"
        + (f"\n\n[반박 대상 — 강세 논지]\n{counter}" if counter else ""))


def _lead(anchor_topic: str, narr_ctx: str, stock_ctx: str, analysts: dict, bull: str, bear: str) -> dict:
    """리드 애널리스트 — debate 판정 → 리포트 유형(Top-down/Bottom-up) + 레이팅. 목차는 고정 템플릿."""
    prompt = (
        "너는 리드 애널리스트다. 아래 애널리스트 평가와 Bull/Bear 논쟁을 보고 **최종 판정**을 내려라. "
        "한쪽으로 치우치지 말고 확률론적으로 종합하되 분명한 콜을 내라.\n"
        "먼저 리포트 유형을 정하라: 산업 동인이 성장을 주도하면 top_down(예: 반도체), 개별 기업·브랜드가 "
        "주도하면 bottom_up(예: 소비재·화장품).\n"
        + RATING_RUBRIC + "\n"
        "JSON만 출력(코드블록·머리말 없이): {"
        '"report_type":"top_down|bottom_up",'
        '"title":"리포트 제목(핵심 주장 한 줄)",'
        '"overall":"종합 판단 2~3문장(핵심 투자 포인트)",'
        '"ratings":[{"code":"종목코드","name":"종목명","rating":"Strong Buy|Buy|Hold|Sell","upside_pct":정수 or null,"rationale":"1~2문장"}]}\n'
        "ratings는 위 [종목 데이터]의 모든 종목에 대해.\n\n"
        f"[앵커 주제] {anchor_topic}\n[산업 자료]\n{narr_ctx}\n\n[종목 데이터]\n{stock_ctx}\n\n"
        f"[애널리스트]\n펀더: {analysts['fundamental']}\n기술: {analysts['technical']}\n수급: {analysts['sentiment']}\n\n"
        f"[Bull]\n{bull}\n\n[Bear]\n{bear}")
    try:
        return _parse_json(_call_claude_code(prompt, model="opus", timeout=360))
    except Exception:
        return {}


def _write_section(title: str, brief: str, anchor_topic: str, ctx: str, ratings_line: str) -> str:
    """규격 섹션 작성 — 고정 목차의 한 파트를 두괄식·필력으로 충분히 전개."""
    body = _call_text(
        f"너는 리서치 리포트 작성자다. '{anchor_topic}' 통합 리포트의 '{title}' 섹션을 서술하라.\n"
        f"[이 섹션이 담을 것] {brief}\n"
        f"{PARA_RULE} 제공 자료·근거에 정박하고, 미래 전망은 근거 기반 논리로(범위+조건부, 단정 금지). "
        "없는 사실·수치 창작 금지. 밸류·멀티플은 12M Fwd PER과 그 변화 추이로만(후행 PER은 시장이 안 보니 쓰지 마라).\n"
        "★분량: 제한을 두지 마라 — **완결성과 논리의 설득력이 최우선**이다. 여러 문단으로 충분히 전개하고, "
        "하나의 주제로 묶기 어려우면 `### 소제목`으로 논리를 구조화해 내러티브를 펼쳐라. 독자에게 상상력과 "
        "확신을 주는 필력으로 써라(건조한 나열 금지).\n"
        "★출력 규칙: **섹션 본문만** 출력한다. 최상위 제목(## / #)·구분선(---)·글자 수 언급('약 660자' 등)·"
        "'아래는 …이다' 같은 메타 문장을 붙이지 마라(섹션 제목은 시스템이 붙임). 단, 본문 내부의 `### 소제목`은 허용.\n"
        f"[종목 레이팅] {ratings_line}\n\n[참고 자료]\n{ctx}", timeout=420)
    body = _clean_section(body)
    return f"## {title}\n\n{body}" if body else ""


def _clean_section(text: str) -> str:
    """작성자 LLM이 흘린 메타(글자수 언급·'아래는…이다'·구분선·자체 제목)를 제거."""
    t = (text or "").strip()
    # 상단 메타 머리말(짧고 '자/섹션/초안/다음/범위' 포함) + 그 뒤 '---' 제거
    head, sep, rest = t.partition("---")
    if sep and len(head) < 200 and any(k in head for k in ("자", "섹션", "초안", "다음", "범위")):
        t = rest.strip()
    # 선두의 '자체 최상위 제목' 라인만 제거 — H1/H2(#, ##)·짧은 **제목**. ### 소제목은 보존.
    lines = t.split("\n")
    while lines:
        first = lines[0].strip()
        is_h12 = first.startswith("#") and not first.startswith("###")
        is_bold_title = first.startswith("**") and first.endswith("**") and len(first) < 40
        if is_h12 or is_bold_title:
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
        else:
            break
    return "\n".join(lines).strip()


def build_report(conn, anchor_topic: str, force: bool = False) -> dict:
    if llm_engine() != "claude-code":
        return {"error": "LLM 엔진 없음 (ENRICH_ENGINE=claude-code 필요)"}
    anchor = _latest_narr(conn, anchor_topic)
    if not anchor:
        return {"error": f"'{anchor_topic}' 내러티브 없음 — 먼저 내러티브를 생성하세요"}

    # A. 앵커 + 공유 이웃
    from pipeline.narrative import related_narratives
    rel = related_narratives(conn, anchor["id"]).get("related", [])
    member_narrs, seen = [dict(anchor)], {anchor_topic}
    for r in rel:
        if r["topic"] in seen:
            continue
        m = _latest_narr(conn, r["topic"])
        if m:
            member_narrs.append(dict(m)); seen.add(r["topic"])
        if len(member_narrs) > TOP_RELATED:
            break
    members = [(m["topic"], m["version"]) for m in member_narrs]
    mhash = _members_hash(members)
    if not force:
        cur = conn.execute(
            "SELECT title, body, stocks_json, members_json, debate_json, members_hash, created_at "
            "FROM reports WHERE anchor_topic=?", (anchor_topic,)).fetchone()
        if cur and cur["members_hash"] == mhash:
            return {"status": "ok", "title": cur["title"], "answer": cur["body"],
                    "members": json.loads(cur["members_json"] or "[]"),
                    "stocks": json.loads(cur["stocks_json"] or "[]"),
                    "debate": json.loads(cur["debate_json"] or "{}"),
                    "cached": True, "created_at": cur["created_at"]}

    # A. 자료 수집 + 종목 다각도 집계 (② 보강 포함)
    narr_material, stock_angles = [], {}
    augment_budget = AUGMENT_CAP
    for m in member_narrs:
        sc = conn.execute("SELECT answer, beneficiaries FROM scenarios WHERE topic=?", (m["topic"],)).fetchone()
        answer = sc["answer"] if sc else None
        bens = json.loads(sc["beneficiaries"]) if (sc and sc["beneficiaries"]) else []
        if not sc and augment_budget > 0:
            augment_budget -= 1
            try:
                from pipeline.scenario import build_scenario
                ev = f"{m['topic']} — {m['title']}" if m.get("title") else m["topic"]
                r = build_scenario(ev)
                if not r.get("error"):
                    answer, bens = r.get("answer"), r.get("beneficiaries") or []
            except Exception:
                pass
        narr_material.append({"topic": m["topic"], "title": m["title"], "body": m["body"], "scenario": answer})
        for b in bens:
            code = b.get("stock_code")
            if not code:
                continue
            slot = stock_angles.setdefault(code, {"name": b.get("name") or code, "angles": []})
            slot["angles"].append({"narrative": m["topic"], "rel": b.get("rel"), "reason": b.get("reason")})

    ranked = sorted(stock_angles.items(), key=lambda kv: -len(kv[1]["angles"]))[:TOP_STOCKS]
    stocks = []
    for c, v in ranked:
        a = _anchor(conn, c)
        # 브리프 재사용(보강) — 종목 심층 콜(수급·상승분해·기술·PER밴드·컨센서스 종합, opus·게으른 캐시).
        # 리포트가 종목 분석을 재발명하지 않고 이미 정합적인 브리프 위에 서게 한다.
        brief = None
        try:
            from pipeline.stock_brief import compute_brief
            brief = compute_brief(c).get("brief")
        except Exception:
            pass
        stocks.append({"code": c, "name": v["name"], "angles": v["angles"], "anchor": a,
                       "sig": _signals(conn, c, v["name"]), "segments": _segments(conn, a.get("corp_code")),
                       "consensus": _consensus(conn, c), "brief": brief})

    narr_ctx, stock_ctx = _narr_ctx(narr_material), _stock_ctx(stocks)

    # B. 애널리스트 팀 (sonnet ×3)
    analysts = {k: _analyst(k, narr_ctx, stock_ctx) for k in ("fundamental", "technical", "sentiment")}
    # C. 리서처 debate (sonnet ×2, Bear는 Bull을 반박)
    bull = _researcher("bull", narr_ctx, stock_ctx, analysts)
    bear = _researcher("bear", narr_ctx, stock_ctx, analysts, counter=bull)
    # D. 리드 판정 (opus ×1) — 리포트 유형 선택 + 레이팅 (목차는 고정 템플릿, 리드 실패해도 진행)
    lead = _lead(anchor_topic, narr_ctx, stock_ctx, analysts, bull, bear)
    ratings = lead.get("ratings") or []
    report_type = lead.get("report_type") if lead.get("report_type") in SECTION_SPECS else "top_down"
    title = lead.get("title") or f"{anchor_topic} 통합 리포트"
    ratings_line = " · ".join(
        f"{r.get('name')} {r.get('rating')}"
        + (f"({round(r['upside_pct'])}%)" if r.get("upside_pct") is not None else "")
        for r in ratings) or "(레이팅 없음)"

    # F. 규격 목차 섹션 작성 (sonnet ×4, 두괄식) → 조립. overall은 리드 판단을 머리말로.
    ctx = (f"{narr_ctx}\n\n[종목 데이터]\n{stock_ctx}\n\n[애널리스트]\n펀더:{analysts['fundamental']}\n"
           f"기술:{analysts['technical']}\n수급:{analysts['sentiment']}\n\n[Bull]{bull}\n\n[Bear]{bear}")
    sections = [_write_section(t, brief, anchor_topic, ctx, ratings_line)
                for t, brief in SECTION_SPECS[report_type]]
    body = "\n\n".join(s for s in sections if s)
    if lead.get("overall"):
        body = f"## 투자 포인트 요약\n\n{lead['overall']}\n\n" + body

    if not body:   # 전 섹션 실패 시에만 저장 안 함
        return {"error": "리포트 생성 실패 (LLM 연쇄)"}

    stocks_out = [{"code": r.get("code"), "name": r.get("name"), "rating": r.get("rating"),
                   "upside_pct": r.get("upside_pct")} for r in ratings]
    debate = {"fundamental": analysts["fundamental"], "technical": analysts["technical"],
              "sentiment": analysts["sentiment"], "bull": bull, "bear": bear,
              "ratings": ratings}
    conn.execute(
        "INSERT INTO reports (anchor_topic, title, body, members_json, stocks_json, debate_json, "
        "members_hash, model, created_at) VALUES (?,?,?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(anchor_topic) DO UPDATE SET title=excluded.title, body=excluded.body, "
        "members_json=excluded.members_json, stocks_json=excluded.stocks_json, "
        "debate_json=excluded.debate_json, members_hash=excluded.members_hash, "
        "model=excluded.model, created_at=excluded.created_at",
        (anchor_topic, title, body, json.dumps([m["topic"] for m in member_narrs], ensure_ascii=False),
         json.dumps(stocks_out, ensure_ascii=False), json.dumps(debate, ensure_ascii=False),
         mhash, "claude-code/opus+sonnet"))
    conn.commit()
    return {"status": "ok", "title": title, "answer": body,
            "members": [m["topic"] for m in member_narrs], "stocks": stocks_out,
            "debate": debate, "cached": False, "created_at": None}

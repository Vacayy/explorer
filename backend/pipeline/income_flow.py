"""분기 손익 흐름(Sankey) 만들기 — ia-redesign §4.13 '분기 손익 흐름'.

- 한국은 기존 financial_statements(DART 분기보고서) 저장분만 읽는다. 잠정공시 숫자 수집은 Stage A2 후속.
- 변환은 순수 함수 build_kr_income_flow(). DB 조립은 kr_income_flow().
- 음수 흐름 금지: 영업외 손익이 음수면 비용 노드로 뒤집는다(절대값).
- 미공시 세부는 지어내지 않음: 세부 못 쪼개면 "영업비용" 합친 노드 하나로 두고 note를 단다.
- 노드마다 들어온 합 = 나간 합(반올림 1% 이내)이어야 그린다. 어긋나면 degraded.
- 법인세·기타 차액 = 세전 − 순이익 같은 식으로 산출한 값은 estimated=True (점선·'차액·추정').
"""
from __future__ import annotations

from typing import Any

from database import get_connection
from models.income_flow import (
    FlowCallout, FlowLink, FlowNode, FlowNodeSubs, FlowSegment,
    IncomeFlowQuarters, IncomeFlowResponse, QuarterItem,
)
from services.dart_service import _build_financial_response, _corp_code_for_stock


REPRT_MONTH = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
MONTH_REPRT = {v: k for k, v in REPRT_MONTH.items()}


def _period_key(year: int, reprt_code: str) -> str:
    return f"{str(year)[2:]}{'.'}{REPRT_MONTH[reprt_code]}"


def _parse_period(label: str) -> tuple[int, str]:
    """'26.06' → (2026, '11012'). 유효성은 호출부에서."""
    yy, mm = label.split(".")
    return (2000 + int(yy), MONTH_REPRT[mm])


def _prev_q_label(label: str) -> str:
    year, reprt = _parse_period(label)
    order = ["11013", "11012", "11014", "11011"]
    i = order.index(reprt)
    if i == 0:
        return _period_key(year - 1, "11011")
    return _period_key(year, order[i - 1])


def _prev_y_label(label: str) -> str:
    year, reprt = _parse_period(label)
    return _period_key(year - 1, reprt)


def _row_lookup(response: dict) -> dict[str, dict[str, float | None]]:
    """FinancialResponse → {account_nm: {period_label: value}}. value는 원(단위) float."""
    periods = response.get("periods", [])
    out: dict[str, dict[str, float | None]] = {}
    for r in response.get("rows", []):
        vals = {}
        for p, v in zip(periods, r.get("values", [])):
            if v is None:
                vals[p] = None
            else:
                try:
                    vals[p] = float(v)
                except (ValueError, TypeError):
                    vals[p] = None
        out[r["account_nm"]] = vals
    return out


def _get(lookup: dict, period: str, *accounts: str) -> float | None:
    """첫 매칭 계정의 값. 여러 이름을 대안으로 받는다."""
    for a in accounts:
        row = lookup.get(a)
        if row is not None and row.get(period) is not None:
            return row[period]
    return None


def _ratio(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom * 100


def _pct_change(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return (cur - base) / abs(base) * 100


def _diff_pp(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None:
        return None
    return cur - base


def _non_operating(lookup: dict, period: str) -> tuple[float, float, dict[str, float]]:
    """(영업외수익 합, 영업외비용 합, 세부 {account_nm: 금액}). 지분법투자 손익은 부호로 가른다."""
    inflow = 0.0
    cost = 0.0
    detail: dict[str, float] = {}

    def add(label: str, v: float | None, bucket: str):
        nonlocal inflow, cost
        if v is None or v == 0:
            return
        detail[label] = detail.get(label, 0.0) + (v if bucket == "inflow" else abs(v))
        if bucket == "inflow":
            inflow += v
        else:
            cost += abs(v)

    add("금융수익", _get(lookup, period, "금융수익"), "inflow")
    add("금융비용", _get(lookup, period, "금융비용"), "cost")
    add("기타영업외수익", _get(lookup, period, "기타영업외수익"), "inflow")
    add("기타영업외비용", _get(lookup, period, "기타영업외비용"), "cost")
    eq = _get(lookup, period, "지분법투자 관련 손익", "지분법손익")
    if eq is not None and eq != 0:
        if eq > 0:
            add("지분법 손익", eq, "inflow")
        else:
            add("지분법 손익", eq, "cost")
    return inflow, cost, detail


def build_kr_income_flow(
    response: dict,
    period: str,
    stage: str,
    as_of: str | None,
    fs_div: str,
    mode: str = "q",
) -> IncomeFlowResponse | None:
    """FinancialResponse(최근 8분기)와 current 분기 라벨을 받아 Sankey 응답을 만든다.

    현 분기의 매출·영업이익·순이익이 모두 비면 None. 매출이 있으면 가능한 만큼 조립.
    """
    lookup = _row_lookup(response)
    prev_q = _prev_q_label(period)
    prev_y = _prev_y_label(period)

    revenue = _get(lookup, period, "매출액")
    op_income = _get(lookup, period, "영업이익")
    net_income = _get(lookup, period, "당기순이익")
    if revenue is None and op_income is None and net_income is None:
        return None

    cogs = _get(lookup, period, "매출원가")
    gross = _get(lookup, period, "매출총이익")
    if gross is None and revenue is not None and cogs is not None:
        gross = revenue - cogs

    sga_total = _get(lookup, period, "판매비와관리비", "영업비용")
    sga_sales = _get(lookup, period, "판매비")
    sga_admin = _get(lookup, period, "관리비")
    rnd = _get(lookup, period, "연구개발비")
    sga_detail_parts = [v for v in (sga_sales, sga_admin, rnd) if v is not None]

    ni_inflow, ni_cost, ni_detail = _non_operating(lookup, period)

    pretax = _get(lookup, period, "법인세비용차감전순이익")
    if pretax is None and op_income is not None:
        pretax = op_income + ni_inflow - ni_cost

    tax = _get(lookup, period, "법인세비용")
    tax_estimated = False
    if tax is None and pretax is not None and net_income is not None:
        tax = pretax - net_income
        tax_estimated = True

    # 노드 조립
    nodes: list[FlowNode] = []
    links: list[FlowLink] = []
    degraded: list[str] = []
    notes: list[str] = []

    def add_node(**kw):
        nodes.append(FlowNode(**kw))

    def add_link(src: str, tgt: str, v: float, estimated: bool = False):
        if v <= 0:
            return
        links.append(FlowLink(source=src, target=tgt, value=v, estimated=estimated))

    # 매출
    if revenue is None:
        return None
    rev_subs = FlowNodeSubs(
        yoy=_pct_change(revenue, _get(lookup, prev_y, "매출액")),
        qoq=_pct_change(revenue, _get(lookup, prev_q, "매출액")),
    )
    add_node(id="revenue", label="매출", value=revenue, column=1, kind="revenue", subs=rev_subs)

    # 매출원가 · 매출총이익
    if cogs is not None and gross is not None and revenue is not None:
        add_node(id="cogs", label="매출원가", value=cogs, column=2, kind="cost",
                 subs=FlowNodeSubs(share_of_revenue=_ratio(cogs, revenue)))
        add_link("revenue", "cogs", cogs)
        gross_subs = FlowNodeSubs(
            margin=_ratio(gross, revenue),
            margin_yoy_pp=_diff_pp(
                _ratio(gross, revenue),
                _ratio(_get(lookup, prev_y, "매출총이익"), _get(lookup, prev_y, "매출액")),
            ),
            margin_qoq_pp=_diff_pp(
                _ratio(gross, revenue),
                _ratio(_get(lookup, prev_q, "매출총이익"), _get(lookup, prev_q, "매출액")),
            ),
        )
        add_node(id="gross_profit", label="매출총이익", value=gross, column=2, kind="keep", subs=gross_subs)
        add_link("revenue", "gross_profit", gross)
        parent_node = "gross_profit"
    elif revenue is not None and op_income is not None:
        # 매출원가·판관비 구분 없음 → "영업비용" 합친 노드로
        opex_total = revenue - op_income
        if opex_total > 0:
            add_node(id="opex_combined", label="영업비용", value=opex_total, column=2, kind="cost",
                     estimated=True,
                     subs=FlowNodeSubs(share_of_revenue=_ratio(opex_total, revenue),
                                        note="매출원가·판관비 구분은 분기보고서 후"))
            add_link("revenue", "opex_combined", opex_total, estimated=True)
        add_node(id="op_income", label="영업이익", value=op_income, column=2, kind="keep",
                 subs=FlowNodeSubs(
                     margin=_ratio(op_income, revenue),
                     yoy=_pct_change(op_income, _get(lookup, prev_y, "영업이익")),
                     qoq=_pct_change(op_income, _get(lookup, prev_q, "영업이익")),
                 ))
        add_link("revenue", "op_income", op_income)
        degraded.append("매출원가·판관비 세부")
        parent_node = None  # 영업이익 바로 다음 세전으로
    else:
        degraded.append("영업이익 하위 세부")
        parent_node = None

    # 영업이익 + 판관비 세부 (매출총이익 아래)
    if parent_node == "gross_profit":
        if sga_detail_parts:
            total_opex = 0.0
            if sga_sales:
                add_node(id="opex_sales", label="판매비", value=sga_sales, column=3, kind="cost",
                         subs=FlowNodeSubs(share_of_revenue=_ratio(sga_sales, revenue)))
                add_link("gross_profit", "opex_sales", sga_sales); total_opex += sga_sales
            if sga_admin:
                add_node(id="opex_admin", label="관리비", value=sga_admin, column=3, kind="cost",
                         subs=FlowNodeSubs(share_of_revenue=_ratio(sga_admin, revenue)))
                add_link("gross_profit", "opex_admin", sga_admin); total_opex += sga_admin
            if rnd:
                add_node(id="opex_rnd", label="연구개발비", value=rnd, column=3, kind="cost",
                         subs=FlowNodeSubs(share_of_revenue=_ratio(rnd, revenue)))
                add_link("gross_profit", "opex_rnd", rnd); total_opex += rnd
        elif sga_total is not None and sga_total > 0:
            add_node(id="opex_sga", label="판매비와관리비", value=sga_total, column=3, kind="cost",
                     subs=FlowNodeSubs(share_of_revenue=_ratio(sga_total, revenue)))
            add_link("gross_profit", "opex_sga", sga_total)
        if op_income is not None:
            op_subs = FlowNodeSubs(
                margin=_ratio(op_income, revenue),
                yoy=_pct_change(op_income, _get(lookup, prev_y, "영업이익")),
                qoq=_pct_change(op_income, _get(lookup, prev_q, "영업이익")),
                margin_yoy_pp=_diff_pp(
                    _ratio(op_income, revenue),
                    _ratio(_get(lookup, prev_y, "영업이익"), _get(lookup, prev_y, "매출액")),
                ),
                margin_qoq_pp=_diff_pp(
                    _ratio(op_income, revenue),
                    _ratio(_get(lookup, prev_q, "영업이익"), _get(lookup, prev_q, "매출액")),
                ),
            )
            add_node(id="op_income", label="영업이익", value=op_income, column=3, kind="keep", subs=op_subs)
            add_link("gross_profit", "op_income", op_income)

    # 영업외 + 세전 — 영업외비용은 영업이익에서 미리 빼고 세전으로 넘긴다(수지 유지)
    if op_income is not None and pretax is not None:
        if ni_inflow > 0:
            inflow_labels = [k for k in ("기타영업외수익", "금융수익", "지분법 손익") if ni_detail.get(k, 0) > 0]
            add_node(id="non_op_income", label="영업외수익", value=ni_inflow, column=4, kind="inflow",
                     subs=FlowNodeSubs(note=", ".join(inflow_labels) or None))
            add_link("non_op_income", "pretax", ni_inflow)
        add_node(id="pretax", label="세전이익", value=pretax, column=4, kind="keep",
                 subs=FlowNodeSubs(yoy=_pct_change(pretax, _get(lookup, prev_y, "법인세비용차감전순이익")),
                                    qoq=_pct_change(pretax, _get(lookup, prev_q, "법인세비용차감전순이익"))))
        add_link("op_income", "pretax", op_income - ni_cost)
        if ni_cost > 0:
            cost_labels = [k for k in ("기타영업외비용", "금융비용", "지분법 손익")
                           if ni_detail.get(k, 0) > 0 and k not in ("기타영업외수익", "금융수익")]
            add_node(id="non_op_expense", label="영업외비용", value=ni_cost, column=4, kind="cost",
                     subs=FlowNodeSubs(share_of_revenue=_ratio(ni_cost, revenue),
                                        note=", ".join(cost_labels) or None))
            add_link("op_income", "non_op_expense", ni_cost)

    # 법인세 · 순이익
    if pretax is not None and tax is not None and net_income is not None:
        if tax > 0:
            add_node(id="tax", label="법인세", value=tax, column=5, kind="cost", estimated=tax_estimated,
                     subs=FlowNodeSubs(effective_tax_rate=_ratio(tax, pretax)))
            add_link("pretax", "tax", tax, estimated=tax_estimated)
        if net_income > 0:
            ni_subs = FlowNodeSubs(
                margin=_ratio(net_income, revenue),
                yoy=_pct_change(net_income, _get(lookup, prev_y, "당기순이익")),
                qoq=_pct_change(net_income, _get(lookup, prev_q, "당기순이익")),
            )
            add_node(id="net_income", label="순이익", value=net_income, column=5, kind="keep", subs=ni_subs)
            add_link("pretax", "net_income", net_income)
        if tax_estimated:
            notes.append("법인세는 세전 − 순이익으로 역산한 추정치입니다")

    # 콜아웃 (§5)
    callout = _callout(revenue, op_income, pretax, net_income, ni_inflow, ni_cost, ni_detail,
                       _pct_change(net_income, _get(lookup, prev_q, "당기순이익")),
                       _pct_change(op_income, _get(lookup, prev_q, "영업이익")))

    # 출처 줄 재료
    if stage == "preliminary":
        notes.append("잠정공시 기준 — 상세는 분기보고서 뜨면 다시 채워집니다")
    if mode == "ttm":
        notes.append("최근 4분기 합 (TTM)")

    return IncomeFlowResponse(
        period=period, prev_q=prev_q, prev_y=prev_y, as_of=as_of, stage=stage,
        fs_div=fs_div, unit="KRW", nodes=nodes, links=links,
        callout=callout, notes=notes, degraded=degraded,
    )


def _callout(revenue, op_income, pretax, net_income, ni_inflow, ni_cost, ni_detail,
             ni_qoq_pct, op_qoq_pct) -> FlowCallout | None:
    """§5 콜아웃 — 조건 맞으면 한 문장. 우선순위 1 → 2."""
    # 규칙 1: 영업외수익이 세전의 30% 이상, 또는 순이익 > 매출
    if net_income is not None and revenue is not None and net_income > revenue:
        top = max(((k, v) for k, v in ni_detail.items() if v > 0 and k not in ("금융비용", "기타영업외비용")),
                  key=lambda x: x[1], default=None)
        item = top[0] if top else "영업외수익"
        margin = f"이익률 {_ratio(op_income, revenue):.1f}%" if op_income and revenue else ""
        return FlowCallout(rule=1,
            text=f"순이익이 커진 건 영업외 {item} 때문이며 일회성일 수 있음. "
                 f"본업은 영업이익 기준({margin})으로 볼 것.")
    if pretax and ni_inflow and ni_inflow / pretax >= 0.30:
        top = max(((k, v) for k, v in ni_detail.items() if v > 0 and k not in ("금융비용", "기타영업외비용")),
                  key=lambda x: x[1], default=None)
        item = top[0] if top else "영업외수익"
        margin = f"이익률 {_ratio(op_income, revenue):.1f}%" if op_income and revenue else ""
        return FlowCallout(rule=1,
            text=f"순이익이 커진 건 영업외 {item} 때문이며 일회성일 수 있음. "
                 f"본업은 영업이익 기준({margin})으로 볼 것.")
    # 규칙 2: 순이익 QoQ − 영업이익 QoQ ≥ 10%p
    if ni_qoq_pct is not None and op_qoq_pct is not None and abs(ni_qoq_pct - op_qoq_pct) >= 10:
        direction = "큰" if ni_qoq_pct > op_qoq_pct else "줄어든"
        return FlowCallout(rule=2,
            text=f"영업이익은 QoQ {op_qoq_pct:+.1f}%인데 순이익은 QoQ {ni_qoq_pct:+.1f}%로 {direction} 차이가 났습니다. "
                 f"영업외 손익의 분기 변동 때문입니다. 본업 흐름은 영업이익 쪽이 더 정확합니다.")
    return None


# ── DB 조립 (라우터에서 호출) ───────────────────────────────────────────────

def kr_income_flow(stock_code: str, q: str | None = None, mode: str = "q") -> IncomeFlowResponse | None:
    """stock_code·분기 라벨(YY.MM, 생략 시 최신)·mode(q=단일 분기, ttm=최근 4분기 합). 자료 없으면 None.

    TTM은 4분기 합이라 Q4 → Q1 경계를 넘어가야 해서 넉넉하게 3년을 받는다. QoQ·YoY 비교 포지션(target·prev_q·prev_y)
    각각 4분기 합이 필요해 결국 최대 7분기(≈2년치) 뒤까지 들어간다.
    """
    corp = _corp_code_for_stock(stock_code)
    if not corp:
        return None
    year_now = int(f"20{(q or '26.12').split('.')[0]}") if q else None
    from datetime import datetime
    end_year = year_now or datetime.now().year
    span = 3 if mode == "ttm" else 2
    resp = _build_financial_response(corp, "IS", "quarterly", end_year - span, end_year, "CFS")
    if not resp["rows"]:
        resp = _build_financial_response(corp, "IS", "quarterly", end_year - span, end_year, "OFS")
        fs_div = "OFS"
    else:
        fs_div = "CFS"
    periods = resp["periods"]
    period = q or (periods[-1] if periods else _latest_preliminary_period(stock_code))
    if not period:
        return None
    # 분기보고서에 그 분기가 들어와 있으면 '본보고' 단계로 그린다
    if period in periods:
        as_of = _disclosed_at(corp, period, fs_div)
        if mode == "ttm":
            resp = _ttm_response_kr(resp, period)
        return build_kr_income_flow(resp, period, stage="quarterly_report", as_of=as_of, fs_div=fs_div, mode=mode)
    # 분기보고서는 아직인데 잠정공시 숫자는 들어왔다 → 간소 Sankey(1단계)
    if mode == "ttm":
        return None   # 잠정만으로는 TTM 계산 불가
    prelim = _preliminary_response_kr(stock_code, period)
    if prelim is None:
        return None
    prelim_resp, as_of, fs_div_p = prelim
    return build_kr_income_flow(prelim_resp, period, stage="preliminary", as_of=as_of, fs_div=fs_div_p, mode="q")


def _ttm_response_kr(resp: dict, target_period: str) -> dict:
    """TTM용 FinancialResponse — target·prev_q·prev_y 각 포지션 값을 '그 포지션으로 끝나는 4분기 합'으로.

    4분기 중 하나라도 None이면 그 포지션 값은 None(부분 합을 지어내지 않음). 라벨은 그대로 두어
    build_kr_income_flow의 YoY/QoQ 조회가 그대로 돈다.
    """
    periods = resp.get("periods", [])
    rows = resp.get("rows", [])
    positions = [target_period, _prev_q_label(target_period), _prev_y_label(target_period)]
    new_rows = []
    for r in rows:
        values_dict = {p: v for p, v in zip(periods, r.get("values", []))}
        new_vals: list[str | None] = []
        for pos in positions:
            qs = [pos]
            for _ in range(3):
                qs.append(_prev_q_label(qs[-1]))
            raws = [values_dict.get(q) for q in qs]
            try:
                if all(v is not None for v in raws):
                    total = sum(float(v) for v in raws)   # type: ignore[arg-type]
                    new_vals.append(str(int(total)))
                else:
                    new_vals.append(None)
            except (ValueError, TypeError):
                new_vals.append(None)
        new_rows.append({"account_nm": r["account_nm"], "values": new_vals, "yoy": []})
    return {"periods": positions, "rows": new_rows, "sj_div": resp.get("sj_div", "IS"),
            "fs_div": resp.get("fs_div", "CFS"), "period_type": "ttm"}


def _latest_preliminary_period(stock_code: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT period FROM kr_preliminary_earnings WHERE stock_code=? "
            "ORDER BY period DESC LIMIT 1", (stock_code,)).fetchone()
    finally:
        conn.close()
    return row["period"] if row else None


def _preliminary_response_kr(stock_code: str, period: str) -> tuple[dict, str | None, str] | None:
    """잠정공시 숫자를 FinancialResponse 모양에 맞춰 반환. 매출·영업이익·순이익 3행만 들어간다 — 세부는 build_kr_income_flow가
    '영업비용' 합친 노드로 처리. 반환 `None`이면 저장분에도 없음."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT period, fs_div, revenue, op_income, net_income, rcept_dt FROM kr_preliminary_earnings "
            "WHERE stock_code=? AND period=?", (stock_code, period)).fetchone()
    finally:
        conn.close()
    if not row or row["revenue"] is None:
        return None
    fs_div = row["fs_div"] or "CFS"
    as_of = row["rcept_dt"]
    rows = [
        {"account_nm": "매출액", "values": [str(int(row["revenue"]))], "yoy": []},
        {"account_nm": "영업이익", "values": [str(int(row["op_income"])) if row["op_income"] is not None else None], "yoy": []},
        {"account_nm": "당기순이익", "values": [str(int(row["net_income"])) if row["net_income"] is not None else None], "yoy": []},
    ]
    return ({"periods": [period], "rows": rows, "sj_div": "IS", "fs_div": fs_div, "period_type": "quarterly"},
            as_of, fs_div)


def _disclosed_at(corp: str, period: str, fs_div: str) -> str | None:
    """financial_statements.fetched_at — 이 corp의 해당 분기 행이 처음 들어온 날(YYYY-MM-DD).
    분기보고서 접수일이 아니라 저장 시각이지만, 근사치로 노출.
    """
    year, reprt = _parse_period(period)
    conn = get_connection()
    row = conn.execute(
        "SELECT MIN(fetched_at) t FROM financial_statements "
        "WHERE corp_code=? AND bsns_year=? AND reprt_code=? AND fs_div=?",
        (corp, year, reprt, fs_div),
    ).fetchone()
    conn.close()
    return row["t"][:10] if row and row["t"] else None


def kr_income_flow_quarters(stock_code: str) -> IncomeFlowQuarters:
    """최근 8분기 중 조립 가능한 것을 최신 → 과거 순으로. 매출·영업이익 둘 다 있어야 포함."""
    corp = _corp_code_for_stock(stock_code)
    if not corp:
        return IncomeFlowQuarters(quarters=[])
    from datetime import datetime
    end_year = datetime.now().year
    resp = _build_financial_response(corp, "IS", "quarterly", end_year - 2, end_year, "CFS")
    fs_div = "CFS"
    if not resp["rows"]:
        resp = _build_financial_response(corp, "IS", "quarterly", end_year - 2, end_year, "OFS")
        fs_div = "OFS"
    lookup = _row_lookup(resp)
    items: list[QuarterItem] = []
    for p in reversed(resp.get("periods", [])):
        rev = _get(lookup, p, "매출액")
        op = _get(lookup, p, "영업이익")
        if rev is None and op is None:
            continue
        items.append(QuarterItem(q=p, stage="quarterly_report", as_of=_disclosed_at(corp, p, fs_div)))
        if len(items) >= 8:
            break
    # 분기보고서에 없지만 잠정공시로 들어온 분기(가장 최근 실적 시즌)는 앞에 끼워 넣는다
    reported = {it.q for it in items}
    conn = get_connection()
    try:
        extras = conn.execute(
            "SELECT period, rcept_dt FROM kr_preliminary_earnings "
            "WHERE stock_code=? ORDER BY period DESC LIMIT 4", (stock_code,)).fetchall()
    finally:
        conn.close()
    for r in extras:
        if r["period"] not in reported:
            items.insert(0, QuarterItem(q=r["period"], stage="preliminary", as_of=r["rcept_dt"]))
    items.sort(key=lambda it: it.q, reverse=True)
    return IncomeFlowQuarters(quarters=items[:8])


# ── 미국(US) ─────────────────────────────────────────────────────────────────
#
# 원천은 pipeline.us_income_is가 적재한 us_quarterly('YYYY-MM' 달력 분기 끝 월).
# 분기 라벨은 캘린더 'YYYY-MM' 그대로 둔다(UI에서 'FY27 Q2' 같은 표시는 프런트). us_fundamentals와 같은 키.

US_METRICS = ("revenue", "cogs", "rnd", "sga", "op_income", "pretax", "tax", "net_income")


def _us_prev_q(label: str) -> str:
    y, m = label.split("-")
    yi, mi = int(y), int(m)
    mi -= 3
    if mi <= 0:
        mi += 12; yi -= 1
    return f"{yi:04d}-{mi:02d}"


def _us_prev_y(label: str) -> str:
    y, m = label.split("-")
    return f"{int(y)-1:04d}-{m}"


def _us_lookup(ticker: str) -> dict[str, dict[str, float]]:
    """{metric: {q: value}}. us_quarterly에서 SEC companyfacts로 들어온 라인만."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT metric, q, value FROM us_quarterly WHERE ticker=? AND metric IN "
            f"({','.join('?' * len(US_METRICS))})",
            (ticker, *US_METRICS),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, float]] = {m: {} for m in US_METRICS}
    for r in rows:
        out[r["metric"]][r["q"]] = r["value"]
    return out


def _mv(lookup: dict, metric: str, q: str) -> float | None:
    v = lookup.get(metric, {}).get(q)
    return float(v) if v is not None else None


def build_us_income_flow(lookup: dict, period: str, mode: str = "q", ticker: str | None = None) -> IncomeFlowResponse | None:
    """us_quarterly 라인을 Sankey 응답으로. 매출이 없으면 None."""
    prev_q = _us_prev_q(period)
    prev_y = _us_prev_y(period)

    revenue = _mv(lookup, "revenue", period)
    cogs = _mv(lookup, "cogs", period)
    rnd = _mv(lookup, "rnd", period)
    sga = _mv(lookup, "sga", period)
    op_income = _mv(lookup, "op_income", period)
    pretax = _mv(lookup, "pretax", period)
    tax = _mv(lookup, "tax", period)
    net_income = _mv(lookup, "net_income", period)

    if revenue is None:
        return None

    nodes: list[FlowNode] = []
    links: list[FlowLink] = []
    degraded: list[str] = []
    notes: list[str] = []

    def add_node(**kw): nodes.append(FlowNode(**kw))

    def add_link(src, tgt, v, estimated=False):
        if v > 0:
            links.append(FlowLink(source=src, target=tgt, value=v, estimated=estimated))

    # 매출
    add_node(id="revenue", label="매출", value=revenue, column=1, kind="revenue",
             subs=FlowNodeSubs(
                 yoy=_pct_change(revenue, _mv(lookup, "revenue", prev_y)),
                 qoq=_pct_change(revenue, _mv(lookup, "revenue", prev_q)),
             ))

    # 매출원가 · 매출총이익
    gross = revenue - cogs if cogs is not None else None
    if cogs is not None and gross is not None:
        add_node(id="cogs", label="매출원가", value=cogs, column=2, kind="cost",
                 subs=FlowNodeSubs(share_of_revenue=_ratio(cogs, revenue)))
        add_link("revenue", "cogs", cogs)
        prev_y_gross = (_mv(lookup, "revenue", prev_y) or 0) - (_mv(lookup, "cogs", prev_y) or 0) if _mv(lookup, "cogs", prev_y) is not None else None
        prev_q_gross = (_mv(lookup, "revenue", prev_q) or 0) - (_mv(lookup, "cogs", prev_q) or 0) if _mv(lookup, "cogs", prev_q) is not None else None
        add_node(id="gross_profit", label="매출총이익", value=gross, column=2, kind="keep",
                 subs=FlowNodeSubs(
                     margin=_ratio(gross, revenue),
                     margin_yoy_pp=_diff_pp(_ratio(gross, revenue), _ratio(prev_y_gross, _mv(lookup, "revenue", prev_y))),
                     margin_qoq_pp=_diff_pp(_ratio(gross, revenue), _ratio(prev_q_gross, _mv(lookup, "revenue", prev_q))),
                 ))
        add_link("revenue", "gross_profit", gross)
    else:
        degraded.append("매출원가")

    # R&D · SG&A · 영업이익
    if gross is not None and op_income is not None:
        parent = "gross_profit"
        if rnd is not None:
            add_node(id="opex_rnd", label="R&D", value=rnd, column=3, kind="cost",
                     subs=FlowNodeSubs(share_of_revenue=_ratio(rnd, revenue)))
            add_link(parent, "opex_rnd", rnd)
        if sga is not None:
            add_node(id="opex_sga", label="SG&A", value=sga, column=3, kind="cost",
                     subs=FlowNodeSubs(share_of_revenue=_ratio(sga, revenue)))
            add_link(parent, "opex_sga", sga)
        add_node(id="op_income", label="영업이익", value=op_income, column=3, kind="keep",
                 subs=FlowNodeSubs(
                     margin=_ratio(op_income, revenue),
                     yoy=_pct_change(op_income, _mv(lookup, "op_income", prev_y)),
                     qoq=_pct_change(op_income, _mv(lookup, "op_income", prev_q)),
                     margin_yoy_pp=_diff_pp(_ratio(op_income, revenue), _ratio(_mv(lookup, "op_income", prev_y), _mv(lookup, "revenue", prev_y))),
                     margin_qoq_pp=_diff_pp(_ratio(op_income, revenue), _ratio(_mv(lookup, "op_income", prev_q), _mv(lookup, "revenue", prev_q))),
                 ))
        add_link(parent, "op_income", op_income)

    # 영업외 (net)로 다룬다 — pretax − op_income
    ni_qoq_pct = None
    op_qoq_pct = _pct_change(op_income, _mv(lookup, "op_income", prev_q)) if op_income is not None else None
    ni_inflow = 0.0
    ni_cost = 0.0
    ni_detail: dict[str, float] = {}
    if op_income is not None and pretax is not None:
        delta = pretax - op_income
        if delta > 0:
            ni_inflow = delta
            ni_detail["기타 영업외수익"] = delta
            add_node(id="non_op_income", label="기타 영업외수익", value=delta, column=4, kind="inflow")
            add_link("non_op_income", "pretax", delta)
        elif delta < 0:
            ni_cost = -delta
            ni_detail["기타 영업외비용"] = -delta
        add_node(id="pretax", label="세전이익", value=pretax, column=4, kind="keep",
                 subs=FlowNodeSubs(
                     yoy=_pct_change(pretax, _mv(lookup, "pretax", prev_y)),
                     qoq=_pct_change(pretax, _mv(lookup, "pretax", prev_q)),
                 ))
        add_link("op_income", "pretax", op_income - ni_cost)
        if ni_cost > 0:
            add_node(id="non_op_expense", label="기타 영업외비용", value=ni_cost, column=4, kind="cost",
                     subs=FlowNodeSubs(share_of_revenue=_ratio(ni_cost, revenue)))
            add_link("op_income", "non_op_expense", ni_cost)

    # 법인세 · 순이익
    if pretax is not None and tax is not None and net_income is not None:
        if tax > 0:
            add_node(id="tax", label="법인세", value=tax, column=5, kind="cost",
                     subs=FlowNodeSubs(effective_tax_rate=_ratio(tax, pretax)))
            add_link("pretax", "tax", tax)
        if net_income > 0:
            add_node(id="net_income", label="순이익", value=net_income, column=5, kind="keep",
                     subs=FlowNodeSubs(
                         margin=_ratio(net_income, revenue),
                         yoy=_pct_change(net_income, _mv(lookup, "net_income", prev_y)),
                         qoq=_pct_change(net_income, _mv(lookup, "net_income", prev_q)),
                     ))
            add_link("pretax", "net_income", net_income)
        ni_qoq_pct = _pct_change(net_income, _mv(lookup, "net_income", prev_q))

    # 콜아웃
    callout = _callout(revenue, op_income, pretax, net_income, ni_inflow, ni_cost, ni_detail,
                       ni_qoq_pct, op_qoq_pct)

    # 세그먼트 — us_segments(EX-99.1 LLM 추출)에 이번 분기가 있으면 채운다. 없으면 비움.
    segments = _us_segments_for(ticker, period, prev_y, prev_q, revenue) if ticker else []
    if not segments and ticker:
        notes.append("사업부 매출은 이 분기 EX-99.1 추출 결과가 아직 없습니다")
    if mode == "ttm":
        notes.append("최근 4분기 합 (TTM)")

    return IncomeFlowResponse(
        period=period, prev_q=prev_q, prev_y=prev_y, as_of=None,
        stage="quarterly_report", fs_div="GAAP", unit="USD",
        nodes=nodes, links=links, segments=segments,
        callout=callout, notes=notes, degraded=degraded,
    )


def _us_segments_for(ticker: str, period: str, prev_y: str, prev_q: str, revenue: float | None) -> list[FlowSegment]:
    """us_segments 에서 티커·이번 분기 세그먼트 + 전년동기·전분기로 YoY/QoQ. 매출 비중도 붙인다."""
    conn = get_connection()
    try:
        rows_cur = conn.execute(
            "SELECT segment_name, revenue FROM us_segments WHERE ticker=? AND q=?", (ticker, period)).fetchall()
        rows_y = conn.execute(
            "SELECT segment_name, revenue FROM us_segments WHERE ticker=? AND q=?", (ticker, prev_y)).fetchall()
        rows_q = conn.execute(
            "SELECT segment_name, revenue FROM us_segments WHERE ticker=? AND q=?", (ticker, prev_q)).fetchall()
    finally:
        conn.close()
    cur = {r["segment_name"]: float(r["revenue"]) for r in rows_cur if r["revenue"] is not None}
    yr = {r["segment_name"]: float(r["revenue"]) for r in rows_y if r["revenue"] is not None}
    qr = {r["segment_name"]: float(r["revenue"]) for r in rows_q if r["revenue"] is not None}
    out: list[FlowSegment] = []
    # 큰 사업부 먼저
    for name, v in sorted(cur.items(), key=lambda kv: kv[1], reverse=True):
        out.append(FlowSegment(
            name=name, value=v,
            yoy=_pct_change(v, yr.get(name)),
            qoq=_pct_change(v, qr.get(name)),
            share=_ratio(v, revenue),
        ))
    return out


def _ttm_us_lookup(lookup: dict, target_period: str) -> dict:
    """target·prev_q·prev_y 포지션에서 '그 포지션으로 끝나는 4분기 합'. 4분기 중 하나라도 비면 그 포지션 None."""
    positions = [target_period, _us_prev_q(target_period), _us_prev_y(target_period)]
    out: dict[str, dict[str, float]] = {m: {} for m in lookup}
    for pos in positions:
        qs = [pos]
        for _ in range(3):
            qs.append(_us_prev_q(qs[-1]))
        for metric, values in lookup.items():
            nums = [values.get(q) for q in qs]
            if all(v is not None for v in nums):
                out[metric][pos] = float(sum(nums))   # type: ignore[arg-type]
    return out


def us_income_flow(ticker: str, q: str | None = None, mode: str = "q") -> IncomeFlowResponse | None:
    lookup = _us_lookup(ticker)
    if not any(lookup.get(m) for m in US_METRICS):
        return None
    period = q or max(lookup["revenue"].keys()) if lookup.get("revenue") else None
    if not period:
        return None
    if mode == "ttm":
        lookup = _ttm_us_lookup(lookup, period)
    return build_us_income_flow(lookup, period, mode=mode, ticker=ticker)


def us_income_flow_quarters(ticker: str) -> IncomeFlowQuarters:
    lookup = _us_lookup(ticker)
    rev = lookup.get("revenue", {})
    items: list[QuarterItem] = []
    for p in sorted(rev.keys(), reverse=True):
        items.append(QuarterItem(q=p, stage="quarterly_report", as_of=None))
        if len(items) >= 8:
            break
    return IncomeFlowQuarters(quarters=items)


"""밸류체인 지도 응답 (pipeline/value_chain · value_chain_lags)."""
from pydantic import BaseModel, Field


class VcCompany(BaseModel):
    code: str
    name: str


class VcPoint(BaseModel):
    ym: str
    yoy: float


class CustomerShare(BaseModel):
    label: str | None              # 이름 공시면 회사명, 익명이면 None
    pct: float                     # 매출 대비 %


class CustomerTrendPoint(BaseModel):
    period_end: str
    top_pct: float                 # 그 분기 최대 고객 비중(%)


class CustomerConcentration(BaseModel):
    period_end: str
    period_kind: str               # Q | FY
    customers: list[CustomerShare]
    top_trend: list[CustomerTrendPoint]


class UsMember(BaseModel):
    ticker: str
    name: str
    metric: str                    # 설비투자 | 매출
    q: str                         # 최신 분기(달력 분기 끝)
    value: float                   # USD
    yoy: float | None
    qoq_delta: float | None = None # 잔액 지표(RPO)의 전 분기 대비 순증가(USD)
    customers: CustomerConcentration | None = None   # 10% 이상 고객 비중(us_customers)


class VcAux(BaseModel):
    series: str
    label: str
    missing: bool                  # 아직 수집되지 않음 — 숨기지 않고 표시
    note: str | None = None        # 이 지표를 이렇게 보는 이유·한계(화면 툴팁)
    period: str | None = None
    yoy_3m: float | None = None
    yoy_3m_prev: float | None = None
    state: str | None = None


class VcMarket(BaseModel):
    ref: str
    label: str
    missing: bool
    as_of: str | None = None
    value: float | None = None
    unit: str | None = None
    change_3m: float | None = None # 약 90일 전 대비 변화(bp 또는 %p)
    change_days: int | None = None # 실제 비교 기간(일) — 이력이 짧으면 90보다 짧다
    state: str | None = None       # 긴축 | 완화 | 유지


class VcPxq(BaseModel):
    hs: str
    item: str
    period: str
    value_yoy: float               # 3개월 금액 YoY(%)
    qty_yoy: float                 # 물량(kg)
    price_yoy: float               # 단가·구성(금액/kg)
    price_share: int | None        # 금액 변화 중 단가 기여(로그, %)
    verdict: str                   # 가격 주도 | 물량 주도 | 동반 | 역행 | 정체


class VcNode(BaseModel):
    key: str
    name: str
    description: str
    tw: list[VcCompany]
    kr: list[VcCompany]
    freq: str = "M"                # M = 월간(3개월 YoY) · Q = 미국 분기 실적(분기 YoY)
    source: str | None = None      # tw(대만 월매출) | us(미국 분기 실적) | kr_trade(한국 수출 HS) | ext(중국 세관·일본 무역통계) | None
    us_members: list[UsMember] = []
    aux: list[VcAux] = []          # 교차 확인 지표(월간 외부 시계열)
    market: list[VcMarket] = []    # 신용·금리 여건(자본 조달 칸)
    pxq: list[VcPxq] = []          # 한국 수출 P×Q 분해
    obs_label: str | None = None   # 분기 관측 원천 설명
    period: str | None = None      # 최신 관측 월·분기
    yoy_3m: float | None
    yoy_3m_prev: float | None
    state: str | None              # 가속 | 둔화 | 전환↑ | 전환↓ | 유지 — 자기 이력 대비(±1σ), 이력이 짧으면 ±10%p
    state_z: float | None = None   # 성장률 변화의 자기 이력 표준편차 배수
    obs_kind: str | None = None    # direct | proxy(업계 전체 통계 — 종목 매출 아님)
    obs_caveat: str | None = None
    series: list[VcPoint]


class VcSignal(BaseModel):
    best_lag: int | None
    corr: float | None
    n: int
    passed: bool
    by_lag: dict[str, float]


class VcEdge(BaseModel):
    from_: str = Field(alias="from")   # JSON 키는 from(예약어라 필드명만 from_)
    to: str
    kind: str                      # supply | capex
    reason: str
    verdict: str                   # 확인 | 부분 | 미확인 | 관측 불가
    lag: int | None = None         # + 공급 쪽이 앞섬, − 수요 쪽이 앞섬 (개월)
    lag_consistent: bool | None = None
    signals: dict[str, VcSignal]

    model_config = {"populate_by_name": True}


class VcDemand(BaseModel):
    key: str
    name: str
    description: str
    obs_label: str | None = None   # 관측 원천(미국 분기 실적·중국 세관 월간) — 없으면 대리 관측만
    freq: str = "Q"                # Q = 분기 YoY · M = 3개월 YoY(외부 월간 시계열)
    us_members: list[UsMember] = []
    aux: list[VcAux] = []
    yoy_3m: float | None = None    # 최신 분기 YoY
    yoy_3m_prev: float | None = None
    state: str | None = None
    state_z: float | None = None
    period: str | None = None
    series: list[VcPoint] = []


class VcAxis(BaseModel):
    key: str
    label: str


class VcCell(BaseModel):
    tier: str
    lane: str


class ValueChainResponse(BaseModel):
    as_of: str | None
    tiers: list[VcAxis] = []           # 스윔레인 열(단계)
    lanes: list[VcAxis] = []           # 스윔레인 행(수요처)
    layout: dict[str, VcCell] = {}     # 칸·수요 → (단계, 레인)
    demands: list[VcDemand]
    nodes: list[VcNode]
    edges: list[VcEdge]
    thresholds: dict[str, float]   # 위약 상위 5% 상관(신호별)


class PropRow(BaseModel):
    stock_code: str
    name: str
    directions: dict[str, str | None]
    agree_up: int
    observed: int


class PropLead(BaseModel):
    leader: str
    leader_name: str
    leader_state: str
    follower: str
    follower_name: str
    follower_state: str | None
    months: int
    verdict: str
    status: str                    # 반영됨 | 대기
    kr: list[VcCompany]


class PropagationResponse(BaseModel):
    as_of: str | None
    waiting: list[PropRow]         # 대만 ↑, 한국 수출·공시 아직
    diverging: list[PropRow]       # 원천끼리 방향 반대
    leads: list[PropLead]          # 확인된 선행 엣지에서 앞선 칸이 방향을 바꿈


class FlowRow(BaseModel):
    key: str
    name: str
    state: str | None
    score: int
    yoy: float | None
    increment_usd: float | None    # 최근 3개월(분기) 전년 대비 증가 금액, USD
    increment_prev_usd: float | None = None     # 직전 창(3개월·한 분기 전)의 증가 금액
    increment_change_usd: float | None = None   # 증가 금액의 변화(흐름의 가속)
    period: str | None
    kind: str                      # flow | stock(잔액 — RPO)
    cross_agree: float | None      # 교차 확인 지표 중 같은 방향 비율
    kr: list[str]
    kr_return_3m: float | None     # 칸 한국 종목 63거래일 수익률 평균
    attention: int                 # 칸 한국 종목 문서 수(최근 30일)
    attention_prev: int
    why: str | None = None
    falsifier: str | None = None
    level_usd: float | None = None # 칸 규모 — 최근 3개월(분기 칸은 최신 분기) 매출·수출액 USD (§14)
    obs_kind: str = "direct"       # direct(붙은 회사 매출) | proxy(업계 전체 수출 통계)
    disclosure_up: int | None = None   # 대리 관측 칸: 붙은 종목 중 공시 방향 up 수
    disclosure_n: int | None = None


class FlowDemand(BaseModel):
    key: str
    name: str
    level_usd: float | None = None
    increment_usd: float | None = None
    level_note: str | None = None   # 규모를 그리지 않는 이유(잔액 지표·관측 없음)


class EdgeFlow(BaseModel):
    from_: str = Field(alias="from")   # JSON 키는 from
    to: str
    flow_usd: float | None          # 추정 — 공급 칸 증가액을 사는 칸 규모 비례로 나눔(거래액 아님)
    basis: str = "estimate"
    buyer_level_imputed: bool = False   # 사는 칸 규모를 몰라 중앙값으로 둠


class FlowResponse(BaseModel):
    as_of: str | None
    twd_usd: float
    median_kr_return_3m: float | None
    median_attention: float
    flows: list[FlowRow]           # 증가 금액이 가장 빨리 늘어나는 칸
    spotlight: list[FlowRow]       # 다음 스포트라이트 가설(조용한 가속)
    doubted: list[FlowRow]         # 흐름은 가속인데 시장이 의심하는 칸
    fading: list[FlowRow]          # 식는 칸
    needs_check: list[FlowRow] = []   # 대리 관측이라 종목 공시로 확인이 필요한 칸
    demands: list[FlowDemand] = []
    edge_flows: list[EdgeFlow] = []
    nodes: list[FlowRow]



class ExpPeriod(BaseModel):
    rev_avg: float | None = None
    rev_growth: float | None = None    # 소수(0.44 = +44%)
    analysts: int | None = None
    eps_avg: float | None = None
    eps_30d: float | None = None
    eps_90d: float | None = None


class ExpMember(BaseModel):
    symbol: str
    name: str
    currency: str | None = None
    snap_date: str
    periods: dict[str, ExpPeriod]      # 0q · +1q · 0y · +1y
    rev_revision_30d: float | None = None


class ExpClaim(BaseModel):
    source: str
    source_org: str | None = None
    published_at: str | None = None
    subject: str | None = None
    metric: str
    target_period: str | None = None
    value_low: float | None = None
    value_high: float | None = None
    unit: str | None = None
    direction: str | None = None
    quote: str | None = None
    url: str | None = None


class ExpNode(BaseModel):
    name: str | None = None
    members: list[ExpMember] = []
    coverage: str
    exp_0q: float | None = None        # 칸 기대 성장률(%) — 이번 분기
    exp_0y: float | None = None        # 올해
    exp_1y: float | None = None        # 내년
    eps_rev_30d: float | None = None   # 올해 EPS 추정 개정 중앙값(%)
    eps_rev_90d: float | None = None
    rev_rev_30d: float | None = None   # 올해 매출 추정 30일 개정 평균(%) — 스냅샷이 28일 이상 쌓인 뒤
    claims: list[ExpClaim] = []
    note: str | None = None            # 기대 구성 회사를 바꾼 이유 등
    observed: float | None = None      # 칸 관측(최근 3개월·최신 분기 YoY)
    observed_period: str | None = None
    obs_kind: str | None = None
    gap_pp: float | None = None        # 관측 − 기대(이번 분기), %p


class ExpGapRow(BaseModel):
    key: str
    name: str
    observed: float
    exp_0q: float
    gap_pp: float
    eps_rev_30d: float | None = None
    eps_rev_90d: float | None = None


class ExpectationsResponse(BaseModel):
    as_of: str | None
    revision_base: str | None = None
    gap_pp: float = 15.0
    nodes: dict[str, ExpNode]
    ahead: list[ExpGapRow] = []        # 관측이 기대보다 크게 높은 칸
    behind: list[ExpGapRow] = []       # 기대가 관측보다 크게 높은 칸



class ChainTreeNode(BaseModel):
    key: str
    name: str
    parent: str | None = None
    depth: int
    flow_usd: float | None = None      # 부모 칸으로 가는 추정 증가액(§14)


class ChainPreview(BaseModel):
    root: str
    tree: list[ChainTreeNode]
    calls: dict[str, int]
    models: dict[str, str]


class ChainRef(BaseModel):
    ref: str                           # D문서번호 · C티커 날짜
    title: str | None = None
    url: str | None = None
    date: str | None = None
    kind: str | None = None


class ChainReport(BaseModel):
    id: int
    root: str
    status: str                        # running | done | partial | error
    progress: str | None = None
    body: str | None = None
    model: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    tree: list[ChainTreeNode] = []
    refs: list[ChainRef] = []
    missing: list[dict] = []


class ChainReportItem(BaseModel):
    id: int
    root: str
    status: str
    created_at: str | None = None
    finished_at: str | None = None

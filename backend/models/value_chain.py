"""밸류체인 지도 응답 (pipeline/value_chain · value_chain_lags)."""
from pydantic import BaseModel, Field


class VcCompany(BaseModel):
    code: str
    name: str


class VcPoint(BaseModel):
    ym: str
    yoy: float


class UsMember(BaseModel):
    ticker: str
    name: str
    metric: str                    # 설비투자 | 매출
    q: str                         # 최신 분기(달력 분기 끝)
    value: float                   # USD
    yoy: float | None
    qoq_delta: float | None = None # 잔액 지표(RPO)의 전 분기 대비 순증가(USD)


class VcAux(BaseModel):
    series: str
    label: str
    missing: bool                  # 아직 수집되지 않음 — 숨기지 않고 표시
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
    source: str | None = None      # tw(대만 월매출) | us(미국 분기 실적) | kr_trade(한국 수출 HS) | None(관측 없음)
    us_members: list[UsMember] = []
    aux: list[VcAux] = []          # 교차 확인 지표(월간 외부 시계열)
    market: list[VcMarket] = []    # 신용·금리 여건(자본 조달 칸)
    pxq: list[VcPxq] = []          # 한국 수출 P×Q 분해
    obs_label: str | None = None   # 분기 관측 원천 설명
    period: str | None = None      # 최신 관측 월·분기
    yoy_3m: float | None
    yoy_3m_prev: float | None
    state: str | None              # 가속 | 둔화 | 전환↑ | 전환↓ | 유지
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
    obs_label: str | None = None   # 관측 원천(미국 분기 실적) — 없으면 대리 관측만
    us_members: list[UsMember] = []
    aux: list[VcAux] = []
    yoy_3m: float | None = None    # 최신 분기 YoY
    yoy_3m_prev: float | None = None
    state: str | None = None
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

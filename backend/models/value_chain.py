"""밸류체인 지도 응답 (pipeline/value_chain · value_chain_lags)."""
from pydantic import BaseModel, Field


class VcCompany(BaseModel):
    code: str
    name: str


class VcPoint(BaseModel):
    ym: str
    yoy: float


class VcNode(BaseModel):
    key: str
    name: str
    description: str
    tw: list[VcCompany]
    kr: list[VcCompany]
    yoy_3m: float | None
    yoy_3m_prev: float | None
    state: str | None              # 가속 | 둔화 | 전환↑ | 전환↓ | 유지 (대만 관측 노드만)
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


class ValueChainResponse(BaseModel):
    as_of: str | None
    demands: list[VcDemand]
    nodes: list[VcNode]
    edges: list[VcEdge]
    thresholds: dict[str, float]   # 위약 상위 5% 상관(신호별)

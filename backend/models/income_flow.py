"""분기 손익 흐름(Sankey) 응답 모델 — ia-redesign §4.13 '분기 손익 흐름'.

프런트 `IncomeFlow` 섹션의 계약. 값은 raw 금액(한국 원, 미국 달러), 라벨·단위·색 토큰은 프런트가 입힌다.
"""
from typing import Literal

from pydantic import BaseModel


class FlowNodeSubs(BaseModel):
    """라벨 아래 보조 숫자. 공시에서 산출 불가한 필드는 None."""
    yoy: float | None = None                 # 전년동기 대비 %
    qoq: float | None = None                 # 전 분기 대비 %
    margin: float | None = None              # 이익률 % (매출 대비)
    margin_yoy_pp: float | None = None       # 이익률 YoY 변화 %p
    margin_qoq_pp: float | None = None       # 이익률 QoQ 변화 %p
    share_of_revenue: float | None = None    # 비용 노드: 매출 대비 비중 %
    effective_tax_rate: float | None = None  # 법인세 노드: 실효세율 %
    note: str | None = None                  # "매출원가·판관비 구분은 분기보고서 후" 등


class FlowNode(BaseModel):
    id: str
    label: str
    value: float                              # 항상 양수
    column: int                               # 0..5 (사업부..순이익)
    kind: Literal['revenue', 'keep', 'cost', 'inflow']
    estimated: bool = False                   # 차액·추정이면 True → 점선
    subs: FlowNodeSubs | None = None


class FlowLink(BaseModel):
    source: str
    target: str
    value: float
    estimated: bool = False


class FlowCallout(BaseModel):
    rule: int                                 # 1 | 2 (§5 규칙 번호)
    text: str


class FlowSegment(BaseModel):
    """사업부 매출 — 공시된 세그먼트만. 없으면 리스트 비움(§6 '없으면 사업부 열 생략')."""
    name: str
    value: float
    yoy: float | None = None
    qoq: float | None = None
    share: float | None = None                # 매출 대비 비중 %


class IncomeFlowResponse(BaseModel):
    period: str                               # KR '26.06' · US 'FY27 Q2' 포맷
    prev_q: str | None                        # 전 분기
    prev_y: str | None                        # 전년 동기
    as_of: str | None                         # 공시 날짜 YYYY-MM-DD (알면)
    stage: Literal['preliminary', 'quarterly_report']
    fs_div: Literal['CFS', 'OFS', 'GAAP']     # US는 GAAP
    unit: Literal['KRW', 'USD']
    derived: bool = False                     # US Q4 = 10-K − 9M 파생 (KR은 항상 False)
    nodes: list[FlowNode]
    links: list[FlowLink]
    segments: list[FlowSegment] = []          # 사업부 매출(비어 있을 수 있음)
    callout: FlowCallout | None
    notes: list[str]                          # 출처 줄에 쓸 설명들
    degraded: list[str]                       # 빠진 세부(사용자에게 노출)


class QuarterItem(BaseModel):
    q: str                                    # '26.06'
    stage: Literal['preliminary', 'quarterly_report']
    as_of: str | None


class IncomeFlowQuarters(BaseModel):
    quarters: list[QuarterItem]               # 최신→과거 순, 최대 8

"""대만 월매출 API — 홈 위젯용 (pipeline/tw_revenue, LLM·네트워크 0)."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from models.tw import KrConfirm, TwLinksResponse, TwRevenueResponse
from models.value_chain import ChainPreview, ChainReport, ChainReportItem, ExpectationsResponse, FlowResponse, PropagationResponse, ValueChainResponse

router = APIRouter(prefix="/api/spine/tw", tags=["spine"])


@router.get("/revenue", response_model=TwRevenueResponse)
def tw_revenue(months: int = Query(36, ge=3, le=120)):
    from pipeline.tw_revenue import read
    return read(months)


@router.get("/links", response_model=TwLinksResponse)
def tw_links(kr: str | None = None):
    """대만 → 한국 연결 — 연결별 대만 신호(3개월 YoY·가속/둔화)와 숫자 근거(시차별 상관)"""
    from pipeline.tw_links import read_links
    return read_links(kr)


@router.get("/value-chain", response_model=ValueChainResponse)
def value_chain():
    """밸류체인 지도 — 노드별 대만 신호, 엣지별 측정 시차·위약 보정 판정 (docs/specs/value-chain.md)"""
    from pipeline.value_chain import read_map
    return read_map()


@router.get("/confirm", response_model=list[KrConfirm])
def kr_confirm(kr: str | None = None):
    """한국 확인 신호 — 대만·수출(HS)·공시 세 원천의 방향 (docs/specs/value-chain.md §4)"""
    from pipeline.kr_confirm import confirm
    from pipeline.tw_links import LINKS
    codes = [kr] if kr else sorted({link[0] for link in LINKS})
    return [confirm(c) for c in codes]


@router.get("/propagation", response_model=PropagationResponse)
def propagation():
    """번지는 중 — 한국 확인 전·엇갈림·선행 경보 (docs/specs/value-chain.md §5)"""
    from pipeline.value_chain import propagation as compute
    return compute()


@router.get("/flow", response_model=FlowResponse)
def value_chain_flow():
    """돈의 흐름·다음 스포트라이트 가설 (docs/specs/value-chain.md §11) — 예측이 아니라 반증 조건이 붙은 가설"""
    from pipeline.value_chain_flow import compute
    return compute()


@router.get("/expectations", response_model=ExpectationsResponse)
def value_chain_expectations():
    """시장 기대치 (docs/specs/value-chain.md §15) — 칸 구성 회사 컨센서스·리서치 전망, 관측과 나란히(섞지 않음)"""
    from pipeline.vc_expectations import with_observed
    return with_observed()


def _valid_root(root: str) -> None:
    from pipeline.value_chain import DEMAND_KEYS, NODE_BY_KEY
    if root not in DEMAND_KEYS and root not in NODE_BY_KEY:
        raise HTTPException(404, f"알 수 없는 칸: {root}")


@router.get("/chain-report/preview", response_model=ChainPreview)
def chain_report_preview(root: str):
    """트리 보고서 생성 전 확인 — 고른 트리(깊이 3·칸 12, 추정 증가액 큰 가지 우선)와 예상 LLM 호출 수 (§16)"""
    _valid_root(root)
    from pipeline.chain_report import preview
    return preview(root)


@router.post("/chain-report", response_model=ChainReport)
def chain_report_create(root: str, background: BackgroundTasks):
    """트리 보고서 생성 — 버튼으로 요청할 때만(비싼 생성은 승인 뒤로). 백그라운드에서 칸 메모(sonnet) → 종합(opus + 웹 검색)"""
    _valid_root(root)
    from pipeline.chain_report import build, read, start
    rid, created = start(root)
    if created:                                       # 이미 같은 루트가 돌고 있으면 그 진행 상태만 돌려준다(중복 생성 방지)
        background.add_task(build, rid, root)
    return read(rid)


@router.get("/chain-report/{rid}", response_model=ChainReport)
def chain_report_get(rid: int):
    from pipeline.chain_report import read
    r = read(rid)
    if not r:
        raise HTTPException(404, "보고서 없음")
    return r


@router.get("/chain-reports", response_model=list[ChainReportItem])
def chain_report_list(root: str):
    from pipeline.chain_report import history
    return history(root)

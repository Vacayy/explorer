"""투자 렌즈 API (docs/specs/investor-lens.md) — 브리프와 동일한 2단 패턴:
GET = LLM 없이 즉시(캐시 + stale) / POST = 재료 변경 시만 생성(멱등).

1차: 가치 렌즈(value). 추세 렌즈(trend)는 재료 미구현이라 GET에서 자연히 빠진다(후속).
"""
from fastapi import APIRouter, HTTPException

from models.lens import LensBundle, LensReading, Quadrant

router = APIRouter(prefix="/api/spine/stock", tags=["spine"])


@router.get("/{stock_code}/lens", response_model=LensBundle)
def get_lens(stock_code: str):
    """캐시된 렌즈 판독 + stale + 4상한 — LLM 호출 없음. 재료·원칙 없는 렌즈는 응답에서 생략."""
    from pipeline.investor_lens import LENS_TYPES, compute_quadrant, peek
    bundle: dict = {"stock_code": stock_code}
    for lt in LENS_TYPES:
        p = peek(stock_code, lt)
        if p:
            bundle[lt] = LensReading(
                lens_type=lt, status=p["status"], body=p["body"], stance=p["stance"],
                signals=p["signals"], created_at=p["created_at"], stale=p["stale"])
    q = compute_quadrant(
        bundle["value"].stance if bundle.get("value") else None,
        bundle["trend"].stance if bundle.get("trend") else None)
    if q:
        bundle["quadrant"] = Quadrant(**q)
    return LensBundle(**bundle)


@router.post("/{stock_code}/lens/compute", response_model=LensReading)
def compute_lens(stock_code: str, type: str = "value", refresh: bool = False):
    """재료가 바뀌었을 때만 LLM 생성 — 멱등. type=value|trend."""
    from pipeline.investor_lens import LENS_TYPES, compute_reading
    if type not in LENS_TYPES:
        raise HTTPException(400, "알 수 없는 렌즈 유형")
    r = compute_reading(stock_code, type, refresh)
    if r.get("status") == "not_found":
        raise HTTPException(404, "종목 엔티티가 없습니다")
    if r.get("status") == "no_principles":
        raise HTTPException(404, f"원칙 원장이 없습니다 (vault/principles/{type}.md)")
    if r.get("status") == "unsupported":
        raise HTTPException(400, "아직 지원하지 않는 렌즈입니다")
    return LensReading(
        lens_type=type, status=r["status"], body=r.get("body"), stance=r.get("stance"),
        signals=r.get("signals", []), created_at=r.get("created_at"))

from fastapi import APIRouter, Query
from models.pricing import PricingExtractResult, PricingResponse
from pipeline import pricing_ledger

router = APIRouter(prefix='/api/spine/pricing', tags=['spine'])


@router.get('', response_model=PricingResponse)
def pricing(weeks: int = Query(8, ge=1, le=26)):
    """시장 프라이싱 원장 — 가격 층·전제 타임라인·이번 주 변화(docs/specs/pricing-ledger.md). 저장 읽기만."""
    return pricing_ledger.read(weeks)


@router.post('/extract', response_model=list[PricingExtractResult])
def extract(limit: int | None = Query(None, ge=1, le=120)):
    """아직 추출하지 않은 브리핑 날짜를 오름차순으로(소급·수동). 하루 LLM 1회."""
    return pricing_ledger.extract_pending(limit)

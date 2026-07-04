from fastapi import APIRouter, Query
from services.dart_service import fetch_disclosures

router = APIRouter(prefix="/api/disclosures", tags=["disclosures"])


@router.get("/{stock_code}")
def get_disclosures(
    stock_code: str,
    kind: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    return fetch_disclosures(stock_code, kind, start, end, page, size)

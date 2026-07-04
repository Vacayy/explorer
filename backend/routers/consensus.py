from fastapi import APIRouter
from services.consensus_service import fetch_consensus

router = APIRouter(prefix="/api/consensus", tags=["consensus"])


@router.get("/{stock_code}")
def get_consensus(stock_code: str):
    return fetch_consensus(stock_code)

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from models.risk import RiskResponse, RiskSnapshotResponse
from pipeline.risk import KEYS, get_risk, snapshot_risk, window

router = APIRouter(prefix='/api/spine/risk', tags=['spine'])


@router.get('', response_model=RiskResponse)
def risk(span: Literal['1m', '3m', '1y', '3y', '5y', '10y', '20y', 'all'] | None = Query(None, alias='range'),
         keys: str | None = Query(None, description='쉼표 구분 계열 키(예: vix,curve). 없으면 전체')):
    """파라미터 없으면 전체 이력(기존 Risk 카드). range·keys는 위젯이 필요한 창만 받는 용도."""
    selected = [k for k in keys.split(',') if k] if keys else None
    if selected and (unknown := set(selected) - set(KEYS)):
        raise HTTPException(422, f"알 수 없는 계열: {', '.join(sorted(unknown))}")
    data = get_risk()
    return window(data, span, selected) if span or selected else data


@router.post('/snapshot', response_model=RiskSnapshotResponse)
def snapshot():
    return snapshot_risk()

from fastapi import APIRouter
from models.risk import RiskResponse, RiskSnapshotResponse
from pipeline.risk import get_risk, snapshot_risk

router = APIRouter(prefix='/api/spine/risk', tags=['spine'])


@router.get('', response_model=RiskResponse)
def risk():
    return get_risk()


@router.post('/snapshot', response_model=RiskSnapshotResponse)
def snapshot():
    return snapshot_risk()

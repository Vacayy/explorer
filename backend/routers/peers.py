"""Read-only published Peer bundle. Never collect or advance observations on GET."""
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from models.peers import PeerRuntime

router = APIRouter(prefix='/api/peers', tags=['peers'])
PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'logs/peer-monitor'
DATA = PROJECT / 'frontend/src/data'
logger = logging.getLogger(__name__)


def read_runtime(root=ROOT, data=DATA, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    try:
        current = json.loads((root / 'current.json').read_text())
        if not isinstance(current, dict):
            raise ValueError('invalid publication envelope')
    except FileNotFoundError:
        current = None
    if current is None:
        catalog = json.loads((data / 'peer-catalog.json').read_text())
        prices = json.loads((data / 'peer-prices.json').read_text())
    else:
        catalog, prices = current['catalog'], current['prices']
        if {c['code'] for c in catalog['companies']} != set(prices['prices']):
            raise ValueError('published catalog/price membership mismatch')
    try:
        attempt = json.loads((root / 'last-attempt.json').read_text())
    except FileNotFoundError:
        attempt = None
    # The pointer and attempt file commit separately; do not show an older error
    # as if it occurred after a newer successful publication.
    if current and attempt and datetime.fromisoformat(attempt['at']) < datetime.fromisoformat(current['publishedAt']):
        attempt = None
    return PeerRuntime.model_validate(dict(catalog=catalog, prices=prices,
        origin='collector' if current else 'seed', publishedAt=current['publishedAt'] if current else None,
        baselineOn=current['baselineOn'] if current else None, lastAttempt=attempt,
        priceAgeDays=max(0, (now.date() - datetime.fromisoformat(prices['asOf']).date()).days),
        snapshotAgeHours=max(0, (now - datetime.fromisoformat(prices['collectedAt'])).total_seconds() / 3600),
        signalStatus='held', signalHoldReason='기업행사 조정·공식 거래일·그룹 독립성 검증 미완료'))


@router.get('/runtime', response_model=PeerRuntime)
def runtime():
    try:
        return read_runtime(ROOT, DATA)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning('Invalid Peer runtime snapshot: %s', exc)
        raise HTTPException(status_code=503, detail='Peer 저장 자료를 읽거나 검증하지 못했습니다. 수집 상태를 확인해 주세요.') from exc

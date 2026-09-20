"""Fixed strategy comparison endpoints; no arbitrary code or source DB paths."""
import threading

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from models.market_backtest import BacktestRequest
from pipeline.market_analysis.backtest_runner import BacktestService
from pipeline.market_analysis.store import Conflict

router = APIRouter(prefix='/backtests', tags=['market-backtests'])
_service = None
_lock = threading.Lock()


def service():
    global _service
    with _lock:
        if _service is None:
            _service = BacktestService()
            _service.start()
        return _service


def respond_error(exc):
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(404, '비교 실행 또는 산출물을 찾을 수 없습니다.') from exc
    if isinstance(exc, Conflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, (ValueError, OSError)):
        raise HTTPException(400, str(exc)) from exc
    raise exc


@router.on_event('startup')
def start_worker():
    service()


@router.on_event('shutdown')
def stop_worker():
    if _service is not None:
        _service.stop()


@router.get('/config')
def config():
    return service().config()


@router.post('')
def create(body: BacktestRequest):
    try:
        return service().create(body.model_dump(mode='json'))
    except Exception as exc:
        respond_error(exc)


@router.get('')
def list_runs(limit: int = Query(30, ge=1, le=100)):
    return service().list(limit)


@router.get('/{run_id}')
def get_run(run_id: str):
    try:
        return service().get(run_id)
    except Exception as exc:
        respond_error(exc)


@router.post('/{run_id}/cancel')
def cancel(run_id: str):
    try:
        return service().cancel(run_id)
    except Exception as exc:
        respond_error(exc)


@router.get('/{run_id}/artifacts/{name}')
def artifact(run_id: str, name: str):
    try:
        item, data = service().artifact(run_id, name)
    except Exception as exc:
        respond_error(exc)
    return Response(data, media_type=item['media_type'], headers={
        'Content-Disposition': f'attachment; filename="{item["name"]}"',
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox",
    })

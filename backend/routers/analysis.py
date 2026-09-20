"""Read-only market analysis API with durable AG-UI replay."""
import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from models.market_analysis import ResumeRequest, RunRequest
from pipeline.market_analysis.runner import AnalysisService
from pipeline.market_analysis.store import Conflict, StoreError, TERMINAL
from routers.backtests import router as backtests_router
from routers.discovery import router as discovery_router

router = APIRouter(prefix="/api/analysis", tags=["market-analysis"])
router.include_router(backtests_router)
router.include_router(discovery_router)
_service = None
_service_lock = threading.Lock()


def service() -> AnalysisService:
    global _service
    with _service_lock:
        if _service is None:
            _service = AnalysisService()
            _service.start()
        return _service


def error(exc: Exception):
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(404, "분석 또는 산출물을 찾을 수 없습니다.") from exc
    if isinstance(exc, Conflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, (ValueError, OSError)):
        raise HTTPException(400, str(exc)) from exc
    raise exc


@router.on_event("startup")
def start_worker():
    service()


@router.on_event("shutdown")
def stop_worker():
    if _service is not None:
        _service.stop()


@router.post("/runs")
def create_run(body: RunRequest):
    try:
        return service().create(body.model_dump(mode="json"))
    except Exception as exc:
        error(exc)


@router.get("/strategies")
def list_strategies():
    from pipeline.market_analysis.strategies import CATALOG_VERSION, catalog
    return {"version": CATALOG_VERSION, "items": catalog()}


@router.get("/runs")
def list_runs(limit: int = Query(30, ge=1, le=100)):
    owner = service()
    return {"items": [owner.store.public(s) for s in owner.store.list(limit)]}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        owner = service()
        return owner.store.public(owner.store.read(run_id))
    except Exception as exc:
        error(exc)


@router.get("/runs/{run_id}/thread")
def thread(run_id: str):
    try:
        return service().store.thread(run_id)
    except Exception as exc:
        error(exc)


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, after: int = Query(0, ge=0)):
    owner = service()
    try:
        owner.store.read(run_id)
        header = request.headers.get("last-event-id")
        if header:
            after = max(after, int(header))
            if after < 0:
                raise ValueError("Invalid event sequence")
    except Exception as exc:
        error(exc)

    async def stream():
        nonlocal after
        idle = 0
        while not await request.is_disconnected():
            batch = await asyncio.to_thread(owner.store.events, run_id, after)
            for event in batch:
                after = event["seq"]
                yield f"id: {after}\ndata: {json.dumps(event, ensure_ascii=False, allow_nan=False)}\n\n"
            state = await asyncio.to_thread(owner.store.read, run_id)
            if state["status"] in TERMINAL | {"waiting_input"}:
                # Drain a final event persisted between the first read and the
                # state transition. Reconnection never starts a second run.
                for event in await asyncio.to_thread(owner.store.events, run_id, after):
                    after = event["seq"]
                    yield f"id: {after}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                return
            idle += 1
            if idle % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str, body: ResumeRequest):
    try:
        return service().resume(run_id, body.interrupt_id, body.payload)
    except Exception as exc:
        error(exc)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    try:
        return service().cancel(run_id)
    except Exception as exc:
        error(exc)


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def artifact(run_id: str, artifact_id: str):
    try:
        item, data = service().store.artifact(run_id, artifact_id)
    except Exception as exc:
        error(exc)
    mime = {"json": "application/json", "csv": "text/csv; charset=utf-8", "png": "image/png"}[item["kind"]]
    # Use a server-authored filename; untrusted source names never enter headers.
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="analysis-{artifact_id}.{item["kind"]}"',
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@router.get("/runs/{run_id}/chart/{code}")
def chart(run_id: str, code: str):
    try:
        return service().chart(run_id, code)
    except Exception as exc:
        error(exc)

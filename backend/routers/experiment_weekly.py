"""Explicit execution endpoints; GET reads saved state only."""
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from models.weekly import ResumeRequest, RunRequest, RunView
from pipeline.weekly import runner
from pipeline.weekly.store import Store

router = APIRouter(prefix="/api/experiments/weekly", tags=["weekly-experiment"])


def perform(fn, *args):
    try:
        return fn(*args)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Weekly 실행 기록을 찾을 수 없습니다")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/runs", response_model=RunView, status_code=202)
def start(body: RunRequest):
    return perform(runner.launch, body)


@router.get("/runs")
def runs(limit: int = Query(30, ge=1, le=100)):
    return Store().list_runs(limit)


@router.get("/runs/{run_id}", response_model=RunView)
def run(run_id: str):
    return perform(Store().get, run_id)


@router.get("/runs/{run_id}/events")
def events(run_id: str):
    store = Store()
    perform(store.get, run_id)
    return store.events(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunView)
def cancel(run_id: str):
    return perform(Store().cancel, run_id)


@router.post("/runs/{run_id}/resume", response_model=RunView, status_code=202)
def resume(run_id: str, body: ResumeRequest):
    return perform(runner.resume, run_id, body)


@router.post("/runs/{run_id}/recover", response_model=RunView)
def recover(run_id: str):
    return perform(Store().recover, run_id)


@router.get("/runs/{run_id}/artifacts/{artifact:path}")
def artifact(run_id: str, artifact: str):
    store = Store()
    perform(store.get, run_id)
    root = store.directory(run_id)
    path = (root / artifact).resolve()
    # Serve report data only, never worker prompts or a path outside this run.
    allowed = {"briefing.html", "briefing.json", "run.json", "events.json", "evidence-index.json", "snapshot.json"}
    is_evidence = len(Path(artifact).parts) == 2 and Path(artifact).parts[0] == "evidence" and path.suffix == ".json"
    is_chart = len(Path(artifact).parts) == 1 and path.suffix == ".svg"
    is_history = bool(re.fullmatch(r"(?:briefing|run|events|evidence-index)-attempt-\d+\.(?:html|json)", artifact))
    if not path.is_relative_to(root) or not path.is_file() or not (artifact in allowed or is_evidence or is_chart or is_history):
        raise HTTPException(404, "허용된 산출물을 찾을 수 없습니다")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

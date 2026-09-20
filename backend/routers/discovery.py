"""App-owned discovery actions; only explicit research POST prepares source data."""
import threading

from fastapi import APIRouter, HTTPException, Query

from models.discovery import (CreateCase, RecommendationRun, ResearchRequest, SaveNote,
                              SaveStrategy, StrategyRun, StrategyVersion)
from pipeline.market_analysis.discovery_service import DiscoveryService
from pipeline.market_analysis.store import Conflict

router = APIRouter(prefix="/discovery", tags=["discovery"])
_service = None
_lock = threading.Lock()


def service():
    global _service
    with _lock:
        if _service is None:
            from routers.analysis import service as analysis_service
            _service = DiscoveryService(analysis_service())
        return _service


def invoke(action):
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(404, "전략·발견·조사 기록을 찾을 수 없습니다.") from exc
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.on_event("startup")
def start_worker():
    service().start()


@router.on_event("shutdown")
def stop_worker():
    if _service:
        _service.stop()


@router.get("/strategies")
def strategies():
    return invoke(lambda: {"items": service().store.list("strategy")})


@router.post("/strategies")
def save_strategy(body: SaveStrategy):
    return invoke(lambda: service().save_strategy(body.model_dump(mode="json")))


@router.post("/strategies/{strategy_id}/versions")
def version_strategy(strategy_id: str, body: StrategyVersion):
    return invoke(lambda: service().save_strategy(body.model_dump(mode="json"), strategy_id))


@router.post("/strategies/{strategy_id}/run")
def run_strategy(strategy_id: str, body: StrategyRun):
    return invoke(lambda: service().run_strategy(strategy_id, body.model_dump(mode="json")))


@router.get("/recommendations")
def recommendations(run_id: str | None = Query(None, pattern=r"^[a-f0-9]{32}$"),
                    stock_code: str | None = Query(None, pattern=r"^[0-9A-Z]{6}$")):
    return invoke(lambda: {"items": service().recommendations(run_id, stock_code)})


@router.post("/recommendations/{recommendation_id}/run")
def run_recommendation(recommendation_id: str, body: RecommendationRun):
    return invoke(lambda: service().run_recommendation(recommendation_id, body.model_dump(mode="json")))


@router.get("/cases")
def cases():
    return invoke(lambda: {"items": service().cases()})


@router.post("/cases")
def create_case(body: CreateCase):
    return invoke(lambda: service().create_case(body.model_dump(mode="json")))


@router.get("/cases/{case_id}")
def case(case_id: str):
    return invoke(lambda: service().case(case_id))


@router.post("/cases/{case_id}/notes")
def save_note(case_id: str, body: SaveNote):
    return invoke(lambda: service().save_note(case_id, body.model_dump(mode="json")))


@router.post("/cases/{case_id}/research")
def research(case_id: str, body: ResearchRequest):
    return invoke(lambda: service().research(case_id, body.model_dump(mode="json")))


@router.post("/cases/{case_id}/research/{research_id}/cancel")
def cancel(case_id: str, research_id: str):
    return invoke(lambda: service().cancel(case_id, research_id))

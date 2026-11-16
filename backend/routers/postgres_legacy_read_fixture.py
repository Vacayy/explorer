"""Unchanged legacy home, macro and search reads over the PG candidate projection.

Only saved-data GET routes are exposed. Routes that may collect, call external
services or write (macro snapshot, prediction detail/pin, forced briefings)
stay unavailable in this private preview.
"""
import sys

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

READ_ROUTES = {'/api/spine/home', '/api/spine/home/ai-activity', '/api/spine/home/predictions',
               '/api/spine/search', '/api/spine/search/today',
               '/api/spine/regimes', '/api/spine/regimes/brk', '/api/spine/regimes/state', '/api/spine/regimes/commentary'}


def install(app, projection):
    import database
    original = database.get_connection
    # Modules bound the original by `from database import get_connection`.
    for module in list(sys.modules.values()):
        if getattr(module, 'get_connection', None) is original:
            module.get_connection = projection.connect
    database.get_connection = projection.connect
    # A few helpers (shared_result, expectation evidence) open DB_PATH directly.
    original_path = database.DB_PATH
    for module in list(sys.modules.values()):
        if getattr(module, 'DB_PATH', None) is original_path:
            module.DB_PATH = projection.stable_path

    from routers import spine_home, spine_regimes, spine_search
    for route in (*spine_home.router.routes, *spine_search.router.routes, *spine_regimes.router.routes):
        if isinstance(route, APIRoute) and route.methods == {'GET'} and route.path in READ_ROUTES:
            app.router.routes.append(route)

    from models.us import UsBriefing
    from pipeline.macro import get_macro
    from pipeline.market_regime import get_regime
    from pipeline.us_briefing import build_briefing
    router = APIRouter()

    @router.get('/api/spine/macro')
    def macro():
        return get_macro()

    @router.get('/api/spine/market-regime')
    def market_regime():
        return get_regime()

    @router.get('/api/spine/us/briefing', response_model=UsBriefing)
    def us_briefing(force: bool = False, trade_date: str | None = None):
        if force:
            raise HTTPException(405, 'Collection is unavailable in the read-only preview')
        return build_briefing(force=False, trade_date=trade_date)

    app.include_router(router)

"""Unchanged legacy home, macro and search reads over the PG candidate projection.

Only saved-data GET routes are exposed; each was run against the projection on
an internet-less network with no external connection, model call or write
attempt. Routes that may collect, call external services or write (macro
snapshot, prediction detail/pin, forced briefings or movers, expired index
refresh) stay unavailable in this private preview.
"""
import sys

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

READ_ROUTES = {'/api/spine/home', '/api/spine/home/ai-activity', '/api/spine/home/predictions',
               '/api/spine/search', '/api/spine/search/today',
               '/api/spine/regimes', '/api/spine/regimes/brk', '/api/spine/regimes/state', '/api/spine/regimes/commentary',
               # Home KR/US/stocks tabs
               '/api/spine/indices/breadth', '/api/spine/credit', '/api/spine/market/{market}/overview', '/api/spine/risk',
               '/api/spine/world/changes', '/api/spine/retail', '/api/spine/trend-leaders', '/api/spine/pricing',
               '/api/spine/tracker/status', '/api/spine/trade/grid', '/api/spine/trade/follow', '/api/spine/trade/highlights',
               '/api/spine/transcript/season', '/api/spine/transcript/season/kr', '/api/spine/groups', '/api/spine/approvals',
               # Portfolio reads (writes need a PG ledger and stay unavailable)
               '/api/portfolio', '/api/portfolio/history', '/api/portfolio/exposure', '/api/portfolio/events',
               '/api/portfolio/flow', '/api/portfolio/thesis', '/api/portfolio/transactions', '/api/portfolio/principles',
               '/api/portfolio/principles/state', '/api/portfolio/alerts'}
LEGACY_ROUTERS = ('spine_home', 'spine_search', 'spine_regimes', 'spine_indices', 'spine_credit', 'spine_market_overview',
                  'spine_risk', 'spine_world', 'spine_retail', 'spine_trend', 'spine_pricing', 'spine_tracker',
                  'spine_trade', 'spine_transcript', 'spine_groups', 'spine_approvals', 'portfolio')


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

    import importlib
    # The owner-gated experimental portfolio adapter is replaced by the legacy reads.
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and route.methods == {'GET'} and route.path in READ_ROUTES)]
    for name in LEGACY_ROUTERS:
        for route in importlib.import_module(f'routers.{name}').router.routes:
            if isinstance(route, APIRoute) and route.methods == {'GET'} and route.path in READ_ROUTES:
                app.router.routes.append(route)

    from models.us import UsBriefing
    from pipeline.macro import get_macro
    from pipeline.market_regime import get_regime
    from pipeline.us_briefing import build_briefing
    from pipeline.indices import get_indices
    from routers import spine_kr
    router = APIRouter()

    @router.get('/api/spine/indices')
    def indices():
        return get_indices()  # the legacy route would schedule a refresh once its cache expires

    @router.get('/api/spine/kr/movers')
    def kr_movers(force: bool = False):
        if force:
            raise HTTPException(405, 'Collection is unavailable in the read-only preview')
        return spine_kr.kr_movers(force=False)

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

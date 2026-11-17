"""Market analysis on the candidate: saved runs, discovery records and the strategy catalog, read without the worker.

The legacy read routes run unchanged over the file stores (logs/market-analysis, logs/market-discovery), copied
from the rehearsal data into the candidate's own volume and moved to the MacBook's latest at the cutover. The
analysis and discovery services are created but never started, so nothing is executed here. Starting, resuming,
cancelling and every discovery action call Claude (a CodeAct model and sandbox): they answer 503 until the Claude
login is in place, instead of reaching the previous stack.
"""
from fastapi import HTTPException
from fastapi.routing import APIRoute

READS = {'/api/analysis/runs',  # the strategy catalog is already a legacy read (postgres_legacy_read_fixture)
         '/api/analysis/runs/{run_id}',
         '/api/analysis/runs/{run_id}/thread', '/api/analysis/runs/{run_id}/events',
         '/api/analysis/runs/{run_id}/artifacts/{artifact_id}', '/api/analysis/runs/{run_id}/chart/{code}',
         '/api/analysis/discovery/strategies', '/api/analysis/discovery/recommendations',
         '/api/analysis/discovery/cases', '/api/analysis/discovery/cases/{case_id}'}
UNAVAILABLE = 'Market analysis runs need the Claude login on the candidate; saved results can be read'


def install(app):
    from pipeline.market_analysis.discovery_service import DiscoveryService
    from pipeline.market_analysis.runner import AnalysisService
    from routers import analysis, discovery
    analysis._service = AnalysisService()  # created, not started: no worker, no model
    discovery._service = DiscoveryService(analysis._service)
    # The discovery routes are mounted under /api/analysis here (their router's own prefix is /discovery).
    routes = [(route, route.path) for route in analysis.router.routes if isinstance(route, APIRoute)]
    routes += [(route, '/api/analysis' + route.path) for route in discovery.router.routes if isinstance(route, APIRoute)
               and not route.path.startswith('/api/')]

    def unavailable():
        raise HTTPException(503, UNAVAILABLE)
    for route, path in routes:
        if 'GET' in route.methods and path in READS:
            app.add_api_route(path, route.endpoint, methods=['GET'], response_model=route.response_model, name=route.name)
        elif 'POST' in route.methods and path != '/api/analysis/refine':
            app.add_api_route(path, unavailable, methods=['POST'], name=f'unavailable {path}')

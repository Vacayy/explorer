"""Market analysis on the candidate: saved runs, discovery records and the strategy catalog, read without the worker.

The legacy read routes run unchanged over the file stores (logs/market-analysis, logs/market-discovery), copied
from the rehearsal data into the candidate's own volume and moved to the MacBook's latest at the cutover. The
analysis and discovery services are created but not started unless runs are enabled. Starting, resuming and cancelling
a run call Claude (a CodeAct model in the candidate broker's sandbox): they answer 503 until enabled after the Claude
login, as every discovery action does, instead of reaching the previous stack.
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
# Starting, resuming and cancelling a run, once enabled (REFACTOR_MARKET_ANALYSIS_RUNS=1, after the Claude login and the
# PM's approval): the legacy routes with the worker started under lowered per-run limits (PM #3 6940939784).
RUNS = {('POST', '/api/analysis/runs'), ('POST', '/api/analysis/runs/{run_id}/resume'),
        ('POST', '/api/analysis/runs/{run_id}/cancel')}


def install(app):
    from pipeline.market_analysis.discovery_service import DiscoveryService
    from pipeline.market_analysis.runner import AnalysisService
    from routers import analysis, discovery
    import os
    runs = os.environ.get('REFACTOR_MARKET_ANALYSIS_RUNS') == '1'
    limits = {'max_calls': int(os.environ.get('REFACTOR_MARKET_ANALYSIS_MAX_CALLS', '20')),
              'max_cost': float(os.environ.get('REFACTOR_MARKET_ANALYSIS_MAX_COST', '1.0')),
              'max_seconds': float(os.environ.get('REFACTOR_MARKET_ANALYSIS_MAX_SECONDS', '900'))}
    analysis._service = AnalysisService(**limits) if runs else AnalysisService()  # not started unless runs are enabled
    if runs:
        analysis._service.start()
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
        elif runs and 'POST' in route.methods and ('POST', path) in RUNS:
            app.add_api_route(path, route.endpoint, methods=['POST'], response_model=route.response_model, name=route.name)
        elif 'POST' in route.methods and path != '/api/analysis/refine':
            app.add_api_route(path, unavailable, methods=['POST'], name=f'unavailable {path}')

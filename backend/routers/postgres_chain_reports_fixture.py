"""The unchanged legacy value-chain report button (POST /api/spine/tw/chain-report) on the candidate.

Its records go to PG (`pipeline.postgres_chain_reports`); the report, history and preview reads stay the legacy
routes (they call the same module). The background build runs under the in-process network guard, like the other
screen computations: its material is the saved rows, and the model calls (with the analysis step's web search)
run as CLI subprocesses.
"""
from fastapi.routing import APIRoute

ROUTE = ('POST', '/api/spine/tw/chain-report')


def install(app, factory):
    from pipeline import chain_report, postgres_chain_reports
    from routers import spine_tw
    from routers.postgres_legacy_read_fixture import _offline
    postgres_chain_reports.install(chain_report, factory)
    legacy_build = chain_report.build

    def build(rid, root, outline='bottom_up'):
        token = _offline.set(True)
        try:
            legacy_build(rid, root, outline)
        finally:
            _offline.reset(token)
    chain_report.build = build
    method, path = ROUTE
    app.router.routes.extend(route for route in spine_tw.router.routes
                             if isinstance(route, APIRoute) and route.path == path and method in route.methods)

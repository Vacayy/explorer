"""Unchanged legacy home, macro and search reads over the PG candidate projection.

Only saved-data GET routes are exposed; each was run against the projection on
an internet-less network with no external connection, model call or write
attempt (DNS included). Routes that may collect, call external services or write (macro
snapshot, prediction detail/pin, forced briefings or movers, expired index
refresh) stay unavailable in this private preview. Because a probe cannot see
every branch (yfinance uses native curl), these routes also run under a network
guard: any outbound connection during them fails and is logged, so a stale cache
falls back to saved data instead of fetching.
"""
import json
import logging
import os
import re
import socket
import sys
from contextvars import ContextVar

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
               '/api/portfolio/principles/state', '/api/portfolio/alerts',
               # Narrative detail panels (the detail itself stays on the PG reader)
               '/api/spine/narrative/{narrative_id}/causal', '/api/spine/narrative/{narrative_id}/chain',
               '/api/spine/narrative/{narrative_id}/diff', '/api/spine/narrative/{narrative_id}/grounding',
               '/api/spine/narrative/{narrative_id}/related', '/api/spine/narrative/mer', '/api/spine/narrative/scenario',
               '/api/spine/narrative/versions', '/api/spine/narrative/version', '/api/spine/world/checkpoint',
               # Earnings-call proxies list and the causal panel's beneficiary screen
               '/api/spine/transcript/proxies', '/api/spine/beneficiary/screen',
               # Proxy boards: empty PG-native tables (writes answer unavailable, pipeline.postgres_proxy_boards)
               '/api/spine/proxy-boards', '/api/spine/proxy-boards/', '/api/spine/proxy-boards/{board_id}',
               '/api/spine/narratives/{narrative_id}/market-today', '/api/spine/follows',
               # Company detail: saved prices, valuation, DART statements and disclosures
               '/api/financials/{stock_code}', '/api/financials/{stock_code}/income-flow',
               '/api/financials/{stock_code}/income-flow/quarters', '/api/kpi/{stock_code}', '/api/disclosures/{stock_code}',
               '/api/stock-prices/{stock_code}', '/api/valuation/{stock_code}',
               # Remaining existing screens (people, Taiwan, thesis, admin, company, US, ...): every
               # legacy GET not served by a PG reader that passed the internet-less probe, including DNS.
               '/api/analysis/strategies', '/api/blog/sources',
               '/api/business/{stock_code}/segments', '/api/companies/{stock_code}', '/api/companies/search',
               '/api/consensus/{stock_code}', '/api/consensus/{stock_code}/history', '/api/industries/',
               '/api/ir-notes/{stock_code}', '/api/signals', '/api/spine/actions', '/api/spine/actions/rights',
               '/api/spine/admin/health', '/api/spine/admin/jobs', '/api/spine/admin/runs',
               '/api/spine/admin/runtime', '/api/spine/causal/activity', '/api/spine/causal/edge/{edge_id}/source',
               '/api/spine/causal/node/{entity_id}/narratives', '/api/spine/causal/worldview/core',
               '/api/spine/causal/worldview/index', '/api/spine/causal/worldview/neighborhood/{entity_id}',
               '/api/spine/chart-structure/{code}', '/api/spine/company-profile/{code}', '/api/spine/credit/history',
               '/api/spine/feed/company-evidence', '/api/spine/feed/company-prices', '/api/spine/groups/{group_id}',
               '/api/spine/groups/{group_id}/digests', '/api/spine/groups/{group_id}/evaluations',
               '/api/spine/groups/{group_id}/reasons', '/api/spine/groups/{group_id}/signals',
               '/api/spine/groups/default-watch', '/api/spine/knowledge/items',
               '/api/spine/knowledge/items/{knowledge_id}/evidence', '/api/spine/knowledge/overview',
               '/api/spine/knowledge/worldview', '/api/spine/narrative-candidates', '/api/spine/narrative/mega',
               '/api/spine/person', '/api/spine/person/followed', '/api/spine/person/home',
               '/api/spine/person/resolve', '/api/spine/proxy-boards/adapters',
               '/api/spine/proxy-boards/adapters/{kind}/catalog', '/api/spine/report', '/api/spine/report/history',
               '/api/spine/report/list', '/api/spine/report/version', '/api/spine/research/candidates',
               '/api/spine/retail/history', '/api/spine/retail/snapshots', '/api/spine/saved',
               '/api/spine/sector-map', '/api/spine/sector-map/chain', '/api/spine/sector-map/members',
               '/api/spine/signals/backtest', '/api/spine/sources/dossier', '/api/spine/sources/health',
               '/api/spine/sources/youtube', '/api/spine/stock/{stock_code}/lens',
               '/api/spine/technical-scan/{code}', '/api/spine/thesis/{audit_id}', '/api/spine/thesis/audits',
               '/api/spine/tracker/{code}', '/api/spine/trade/{hs_code}', '/api/spine/trade/{hs_code}/metrics',
               '/api/spine/trade/by-stock/{stock_code}', '/api/spine/transcript/chain/{transcript_id}',
               '/api/spine/transcript/chain/upcoming/{ticker}', '/api/spine/transcript/collect/status',
               '/api/spine/transcript/detail/{transcript_id}/reaction', '/api/spine/transcript/season/sector/{key}',
               '/api/spine/trend-leaders/{code}/chart', '/api/spine/tw/chain-report/preview',
               '/api/spine/tw/chain-reports', '/api/spine/tw/expectations', '/api/spine/tw/flow',
               '/api/spine/tw/revenue', '/api/spine/tw/value-chain', '/api/spine/us', '/api/spine/us/{ticker}',
               '/api/spine/us/{ticker}/income-flow', '/api/spine/us/{ticker}/income-flow/quarters',
               '/api/spine/us/{ticker}/mentions', '/api/spine/us/{ticker}/prices/status',
               '/api/spine/us/{ticker}/worldmodel', '/api/spine/us/briefing/list', '/api/spine/us/briefing/sources',
               '/api/spine/world/big-picture', '/api/spine/world/contested', '/api/spine/world/my-stocks',
               '/api/stock-prices/{stock_code}/snapshot', '/api/telegram/channels'}
# Excluded after the probe: /api/spine/quotes and /api/spine/us/movers fetch external quotes;
# /api/analysis/runs needs a writable run store.


_offline = ContextVar('legacy_read_offline', default=False)
log = logging.getLogger(__name__)


def _refuse(kind, target):
    log.warning('Blocked %s from a legacy read: %s', kind, str(target)[:80])
    raise OSError('Network is unavailable to legacy reads in this preview')


def _install_network_guard(database_host):
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    # The candidate's own PostgreSQL stays reachable; psycopg resolves it in Python.
    allowed = {database_host} | {info[4][0] for info in resolve(database_host, None)}

    def guarded_connect(self, address):
        if _offline.get() and isinstance(address, tuple) and address[0] not in allowed:
            _refuse('connect', address)
        return connect(self, address)

    def guarded_resolve(host, *args, **kwargs):
        if _offline.get() and host not in allowed:
            _refuse('resolve', host)
        return resolve(host, *args, **kwargs)
    socket.socket.connect, socket.getaddrinfo = guarded_connect, guarded_resolve
    try:
        from curl_cffi.requests import Session
    except ImportError:
        return
    request = Session.request

    def guarded_request(self, method, url, *args, **kwargs):
        if _offline.get():
            _refuse('curl request', url)
        return request(self, method, url, *args, **kwargs)
    Session.request = guarded_request


def install(app, projection, *, database_host):
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
    # shared_result reuses a result while the file's data_version is unchanged; projection files never
    # change in place, so key it on the file the stable path points at (a new build is a new key).
    from services import shared_result
    # A requester other than the operator reads no personal state (pipeline.postgres_legacy_projection), so
    # results computed for one class are never handed to the other.
    from pipeline.postgres_legacy_projection import requester_is_operator
    shared_result._db_state = lambda: (os.path.realpath(projection.stable_path), requester_is_operator())

    import importlib
    # The owner-gated experimental portfolio adapter is replaced by the legacy reads.
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and route.methods == {'GET'} and route.path in READ_ROUTES)]
    import pkgutil
    import routers
    first_legacy = len(app.router.routes)
    names = [m.name for m in pkgutil.iter_modules(routers.__path__) if not m.name.startswith('postgres_')]
    from fastapi import APIRouter as _APIRouter
    for name in names:
        module = importlib.import_module(f'routers.{name}')
        # Every router of the module (some keep a second one, e.g. spine_causal.beneficiary_router).
        for router in [value for value in vars(module).values() if isinstance(value, _APIRouter)]:
            for route in router.routes:
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

    # Fixed wrapper paths (e.g. /us/briefing) must win over legacy patterns like /us/{ticker}.
    wrappers = [route for route in router.routes]
    app.router.routes[first_legacy:first_legacy] = wrappers

    _install_network_guard(database_host)
    # Price and DART reads refresh an expired cache before reading the table; here
    # the saved rows are always served (other is_cached users keep their meaning).
    import importlib as _importlib
    for name in ('services.krx_service', 'services.dart_service'):
        service = _importlib.import_module(name)
        service.is_cached = (lambda key, original=service.is_cached: True if _offline.get() else original(key))
    _install_offline_fetches(projection.factory)
    patterns = [re.compile('^' + re.sub(r'\\{[^}]+\\}', '[^/]+', re.escape(path)) + '$')
                for path in READ_ROUTES | {route.path for route in router.routes}]

    @app.middleware('http')
    async def legacy_reads_offline(request, call_next):
        if not any(pattern.match(request.url.path) for pattern in patterns):
            return await call_next(request)
        token = _offline.set(True)  # copied into the threadpool that runs sync endpoints
        try:
            return await call_next(request)
        finally:
            _offline.reset(token)


def _install_offline_fetches(factory):
    """Fetches a legacy computation makes on the way (US daily prices, target-price changes, yfinance estimates):
    offline, the saved rows answer and each skipped fetch is kept as a not-run collection request (the candidate
    does not collect). yfinance goes through curl_cffi, below the socket guard, so it is refused explicitly."""
    import yfinance
    from psycopg.types.json import Jsonb
    from pipeline import earnings_chain, us_data

    def skipped(kind, **params):
        with factory() as pg:
            if not pg.execute("SELECT 1 FROM collector_requests WHERE kind=%s AND params=%s AND status='not_run' "
                              "AND requested_at > now() - interval '1 day'", (kind, Jsonb(params))).fetchone():
                pg.execute("INSERT INTO collector_requests(kind,params,origin) VALUES (%s,%s,'candidate')", (kind, Jsonb(params)))
        return 0

    fetch_prices, refresh_pt, ticker = us_data.fetch_prices, earnings_chain.refresh_pt, yfinance.Ticker
    us_data.fetch_prices = lambda symbol, period='2y', force=False: (
        skipped('us_prices', ticker=symbol.upper()) if _offline.get() else fetch_prices(symbol, period, force))
    earnings_chain.refresh_pt = lambda conn, symbol, max_age_hours=20: (
        skipped('us_pt_changes', ticker=symbol) if _offline.get() else refresh_pt(conn, symbol, max_age_hours))

    quant_snapshot = earnings_chain.quant_snapshot

    def offline_quant(conn, symbol, event_date, with_options):
        # Consensus, estimate revisions and the option-implied move come from yfinance: not collected here; the
        # values saved for this event answer instead, and the gap says so (not a fetch error).
        out = quant_snapshot(conn, symbol, event_date, with_options)
        if not _offline.get():
            return out
        out.pop('estimate_error', None)
        saved = conn.execute("SELECT quant_json FROM earnings_expectations WHERE ticker=? AND event_date=? AND quant_json IS NOT NULL "
                             "ORDER BY CASE snapshot WHEN 'd1' THEN 0 ELSE 1 END LIMIT 1", (symbol, event_date)).fetchone()
        old = json.loads(saved[0]) if saved else {}
        reused = [key for key in ('eps_est', 'rev_est', 'eps_rev_up30', 'eps_rev_down30', 'implied_move')
                  if out.get(key) is None and old.get(key) is not None]
        out.update({key: old[key] for key in reused})
        out['not_run'] = ('컨센서스·추정치 수정·옵션 내재 변동폭은 후보에서 수집하지 않음'
                          + (' (저장값 사용)' if reused else ''))
        skipped('us_estimates', ticker=symbol)
        return out
    earnings_chain.quant_snapshot = offline_quant

    class Blocked:
        # Legacy code builds the Ticker before its try block and reads it inside; refuse at the read.
        def __getattr__(self, name):
            raise RuntimeError('external request blocked: yfinance')

    def offline_ticker(*args, **kwargs):
        return Blocked() if _offline.get() else ticker(*args, **kwargs)
    yfinance.Ticker = offline_ticker

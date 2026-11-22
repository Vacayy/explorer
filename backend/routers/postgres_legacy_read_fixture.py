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
               '/api/spine/person/resolve', '/api/spine/person/{entity_id:int}',
               '/api/spine/person/{name}/dossier', '/api/spine/company/{name}/dossier', '/api/spine/proxy-boards/adapters',
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
               '/api/spine/trend-leaders/{code}/chart', '/api/spine/tw/chain-report/preview', '/api/spine/tw/chain-report/{rid}',
               '/api/spine/tw/chain-reports', '/api/spine/tw/expectations', '/api/spine/tw/flow',
               '/api/spine/tw/revenue', '/api/spine/tw/value-chain', '/api/spine/tw/links', '/api/spine/tw/confirm',
               '/api/spine/tw/propagation', '/api/spine/curation', '/api/spine/client-errors', '/api/spine/us', '/api/spine/us/{ticker}',
               '/api/spine/us/{ticker}/income-flow', '/api/spine/us/{ticker}/income-flow/quarters',
               '/api/spine/us/{ticker}/mentions', '/api/spine/us/{ticker}/prices/status',
               '/api/spine/us/{ticker}/worldmodel',
               '/api/spine/world/big-picture', '/api/spine/world/contested', '/api/spine/world/my-stocks',
               '/api/stock-prices/{stock_code}/snapshot', '/api/telegram/channels'}
# Excluded after the probe: /api/spine/quotes and /api/spine/us/movers fetch external quotes;
# /api/analysis/runs needs a writable run store.


_offline = ContextVar('legacy_read_offline', default=False)
# A route-scoped exception to the guard (architect #3 6941713176): host names this request may still reach while
# offline, and the addresses they resolved to (only those may be connected to).
_external_hosts = ContextVar('legacy_read_external_hosts', default=frozenset())
_external_addresses = ContextVar('legacy_read_external_addresses', default=None)
log = logging.getLogger(__name__)


def _refuse(kind, target):
    log.warning('Blocked %s from a legacy read: %s', kind, str(target)[:80])
    raise OSError('Network is unavailable to legacy reads in this preview')


def _install_network_guard(database_host):
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    # The candidate's own PostgreSQL stays reachable; psycopg resolves it in Python.
    allowed = {database_host} | {info[4][0] for info in resolve(database_host, None)}

    def guarded_connect(self, address):
        if _offline.get() and isinstance(address, tuple) and address[0] not in allowed \
                and address[0] not in (_external_addresses.get() or ()):
            _refuse('connect', address)
        return connect(self, address)

    def guarded_resolve(host, *args, **kwargs):
        if _offline.get() and host not in allowed:
            if host not in _external_hosts.get():
                _refuse('resolve', host)
            infos = resolve(host, *args, **kwargs)
            addresses = _external_addresses.get()
            if addresses is not None:
                addresses.update(info[4][0] for info in infos)
            return infos
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


QUOTE_HOST = 'polling.finance.naver.com'
QUOTE_CODES = 50
QUOTE_BACKOFF = 30
_quote_backoff = [0.0]


def live_quotes(codes):
    """The legacy Naver polling fetch (10-second cache) with the guard open to QUOTE_HOST only; after an upstream
    failure the source is left alone for QUOTE_BACKOFF seconds (the cached value, or nothing, answers meanwhile)."""
    import time as _time
    from pipeline import quotes as live
    if _time.monotonic() < _quote_backoff[0]:
        return (live._cache.get(','.join(sorted(set(codes)))) or (0, []))[1]
    hosts, addresses = _external_hosts.set(frozenset({QUOTE_HOST})), _external_addresses.set(set())
    offline = _offline.set(True)
    try:
        got = live.fetch_quotes(list(codes))
    finally:
        _offline.reset(offline)
        _external_addresses.reset(addresses)
        _external_hosts.reset(hosts)
    if codes and not got:
        _quote_backoff[0] = _time.monotonic() + QUOTE_BACKOFF
    return got


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
    # Each requester reads only its own personal state (pipeline.postgres_legacy_projection), so a result
    # computed for one requester is never handed to another.
    from pipeline.postgres_legacy_projection import requester_scope
    from pipeline import postgres_live_tables
    # Live tables come from PG per connection, not the file: their version is part of the key too.
    shared_result._db_state = lambda: (os.path.realpath(projection.stable_path), requester_scope(),
                                       postgres_live_tables._cache['version'])

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
    from routers import spine_kr, spine_us
    from models.kalshi import KalshiDetail
    from fastapi import Path, Query
    from models.us import UsMoversResponse
    from routers.spine_quotes import Quote
    router = APIRouter()

    def from_pg(screen, compute):
        """The legacy read on the screen's rows from PG (pipeline.postgres_screen_reads, D-294); the projection file
        answers only when that read fails."""
        from pipeline import postgres_screen_reads
        try:
            return postgres_screen_reads.answer(projection.factory, screen, compute)
        except Exception as exc:  # noqa: BLE001
            log.warning('%s PG read failed (%s); answered from the projection', screen, type(exc).__name__)
            return compute()

    @router.get('/api/spine/indices')
    def indices():
        return from_pg('indices', get_indices)  # the legacy route would schedule a refresh once its cache expires

    @router.get('/api/spine/kr/movers')
    def kr_movers(force: bool = False):
        if force:
            raise HTTPException(405, 'Collection is unavailable in the read-only preview')
        return spine_kr.kr_movers(force=False)

    @router.get('/api/spine/macro')
    def macro():
        return from_pg('macro', get_macro)

    @router.get('/api/spine/market-regime')
    def market_regime():
        return from_pg('regime', get_regime)

    @router.get('/api/spine/home/predictions/{event_ticker}', response_model=KalshiDetail)
    def prediction_detail(event_ticker: str = Path(..., pattern=r'^[A-Za-z0-9._-]{1,80}$'),
                          range: str = Query('3m', pattern=r'^(1m|3m|1y)$')):
        from pipeline.kalshi import detail
        try:
            return detail(event_ticker, range, stored_only=True)  # the stored event and candles; Kalshi is not called
        except LookupError:
            raise HTTPException(404, 'Stored prediction detail unavailable') from None

    @router.get('/api/spine/us/movers', response_model=UsMoversResponse)
    def us_movers(force: bool = False):
        if force:
            raise HTTPException(405, 'Collection is unavailable in the read-only preview')
        return spine_us.us_movers(force=False)  # an expired cache answers stale/error offline, never refetches

    @router.get('/api/spine/quotes', response_model=list[Quote])
    def quotes(codes: str):
        # The legacy live-price proxy (Naver polling, 10-second cache), the only legacy read allowed to go out, and
        # only to that host. At most QUOTE_CODES codes; after an upstream failure the source is left alone for
        # QUOTE_BACKOFF seconds (the cached value, or nothing, answers meanwhile). Anonymous callers share the
        # per-network minute limit (pipeline.postgres_usage_gate).
        wanted = [code.strip() for code in codes.split(',') if code.strip()]
        if len(wanted) > QUOTE_CODES or any(not re.fullmatch(r'[0-9A-Z]{6}', code) for code in wanted):
            raise HTTPException(422, f'Up to {QUOTE_CODES} six-character stock codes')
        return [Quote(**q) for q in live_quotes(wanted)]

    # The rest of the US briefing screen, read straight from PG (no in-memory file); the projection answers only
    # when the PG read fails.
    from models.us import UsBriefingListItem, UsBriefingSources
    from pipeline import us_briefing as legacy_briefing

    @router.get('/api/spine/us/briefing/list', response_model=list[UsBriefingListItem])
    def us_briefing_list(limit: int = 30):
        from pipeline import postgres_us_briefing
        try:
            with projection.factory() as pg:
                items = postgres_us_briefing.list_briefings(pg, limit)
        except Exception as exc:  # noqa: BLE001
            log.warning('US briefing list PG read failed (%s); answered from the projection', type(exc).__name__)
            items = legacy_briefing.list_briefings(limit=limit)
        return [UsBriefingListItem(**item) for item in items]

    @router.get('/api/spine/us/briefing/sources', response_model=UsBriefingSources)
    def us_briefing_sources():
        from pipeline import postgres_us_briefing
        try:
            with projection.factory() as pg:
                return UsBriefingSources(**postgres_us_briefing.briefing_sources(pg))
        except Exception as exc:  # noqa: BLE001
            log.warning('US briefing sources PG read failed (%s); answered from the projection', type(exc).__name__)
            return UsBriefingSources(**legacy_briefing.briefing_sources())

    @router.get('/api/spine/us/briefing', response_model=UsBriefing)
    def us_briefing(force: bool = False, trade_date: str | None = None):
        if force:
            raise HTTPException(405, 'Collection is unavailable in the read-only preview')
        # Read from PG (pipeline.postgres_us_briefing): the projection's answer without its file; the file answers
        # only when that read fails.
        from pipeline import postgres_us_briefing
        try:
            return postgres_us_briefing.build_briefing(projection.factory, trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001
            log.warning('US briefing PG read failed (%s); answered from the projection', type(exc).__name__)
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

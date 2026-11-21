"""Collection jobs on the isolated path (backend/pipeline/postgres_isolated_collect.py): extseries and sectorbench.

Per run: the tables the job owns are seeded from PG into a private SQLite file (other tables are read from the
projection, attached read-only, so a stray write fails instead of landing anywhere); each source runs in turn and a
failed source's writes are rolled back; the rest is published by key with the run record and the per-source state in
one transaction. A 403/429 or a host reaching its cap refuses that host's further requests only, so the sources on
other hosts go on. Outcomes: applied, partial (some sources failed; the rest published), failed (nothing to publish),
held back (a check failed or whether the publication took effect is unknown: the scheduler holds all collection).

  python scripts/refactor_collect_job.py extseries|sectorbench   # dispatched from there
"""
import importlib
import inspect
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Jobs that only write their own tables run their unchanged legacy script on the private file (one source).
LEGACY = {'credit': ('credit_bonds', 'credit_quotes', 'treasury_curve'),
          'retail': ('retail_flows', 'retail_snapshots'),
          'twrevenue': ('tw_monthly_revenue',),
          'kalshi': ('kalshi_candles', 'kalshi_events'),  # pins are read from the projection (the owner's ledger)
          'indexintraday': ('index_intraday',),
          # trade_follow is the owner's ledger (read from the projection); beneficiaries the screen computes go to the
          # owner overrides, which stay on top of these rows as before
          'trade': ('trade_stats', 'trade_beneficiaries'),
          # us_prices is the market job's; cache_meta and market_indicators are shared with jobs still on the shared
          # file (published by key here, the keys mirrored into that file)
          'market': ('cache_meta', 'market_indicators', 'us_prices')}
JOBS = ('extseries', 'sectorbench', 'prices', 'pricefix', 'pricefactors', *LEGACY)
# Requests per source host and run; a key starting with '.' covers every host under that domain.
CAPS = {'extseries': {'': 30},
        # Naver realtime quotes in batches of 200 codes (about 15), then Yahoo for the gaps of the last 10 days
        # (+ Naver daily prices and DART disclosures for the few closes beyond the daily limit)
        # KRX (data.krx.co.kr) blocked the address for a day after about 240 rapid lookups of a past-day sweep (KDM
        # notice, 2026-11-21). A run asks 3 listings a day for up to KRX_DAYS_PER_RUN days (+3 per listing-day check),
        # paced: about 4 on an ordinary day, at most 30 when catching up
        'prices': {'': 20, 'polling.finance.naver.com': 30, '.finance.yahoo.com': 300, 'data.krx.co.kr': 30},
        'pricefix': {'': 20, 'data.krx.co.kr': 30},  # + the previous day's listing when a listing day is checked
        'pricefactors': {'': 20, 'data.krx.co.kr': 600},  # not run: see run()
        # credit (macbook-source #3 6942831447): 34 companies' issuer scan, symbol search fallback, 10 FRED series
        'credit': {'': 20, 'scanner.tradingview.com': 150, 'symbol-search.tradingview.com': 60,
                   'data.tradingview.com': 150, 'fred.stlouisfed.org': 12},
        'retail': {'': 20}, 'twrevenue': {'': 20}, 'indexintraday': {'': 20},
        # four categories, up to 18 trending events and pinned-event lookups/candles
        'kalshi': {'': 20, 'api.elections.kalshi.com': 60},
        'trade': {'': 20, 'apis.data.go.kr': 60},  # followed HS codes, 24 months when the source moved on
        # indices, F&G, VKOSPI, the regime tickers (full history once) and FRED series for the market read
        'market': {'': 20, '.finance.yahoo.com': 60, 'fred.stlouisfed.org': 30, 'api.stock.naver.com': 10},
        # 14 KR ETFs + KOSPI one by one, the US ETF batch, then sector info of followed tickers due for refresh
        'sectorbench': {'': 20, '.yahoo.com': 120}}
TABLES = {**LEGACY, 'extseries': ('ext_series', 'expectation_claims'), 'prices': ('stock_prices',), 'pricefix': ('stock_prices',),
          'pricefactors': (),
          'sectorbench': ('sector_benchmark_prices', 'sector_index', 'us_ticker_sectors')}
BACKFILL_AFTER_DAYS = 45  # a source failing longer than its daily window re-reads its whole history once it answers
SHRINK_LIMIT = 0.5
INDEX_KEEP = 0.9  # the computed sector index replaces the last good one only when it is about as complete


class Refused(RuntimeError):
    """A request not sent: its host answered 403/429 or reached its cap earlier in this run."""


class Network:
    """Per-host request count and stop rules of one run; a stop refuses that host only."""

    def __init__(self, caps):
        self.caps, self.requests, self.statuses, self.stopped = caps, Counter(), Counter(), {}

    def cap(self, host):
        if host in self.caps:
            return self.caps[host]
        return next((cap for key, cap in self.caps.items() if key.startswith('.') and host.endswith(key)), self.caps[''])

    @staticmethod
    def host(url):
        return re.sub(r'^https?://([^/:]+).*$', r'\1', str(url))

    def before(self, url):
        host = self.host(url)
        if host in self.stopped:
            raise Refused(self.stopped[host])
        if self.requests[host] >= self.cap(host):
            self.stopped[host] = f'{host} reached the request cap {self.cap(host)}'
            raise Refused(self.stopped[host])
        self.requests[host] += 1

    def after(self, status, url):
        host = self.host(url)
        self.statuses[f'{host} {status}'] += 1
        if status in (403, 429):
            self.stopped.setdefault(host, f'{host} answered {status}')

    def install(self):
        # Clients that do not go through an HTTP library (a websocket quote feed) are counted when they resolve the host:
        # a stopped host is refused, and so many connections count against the host's cap as requests would.
        import socket
        resolve = socket.getaddrinfo
        resolved = Counter()

        def getaddrinfo(host, *args, **kwargs):
            if isinstance(host, str) and host not in ('pg', 'localhost', '127.0.0.1'):
                if host in self.stopped:
                    raise Refused(self.stopped[host])
                resolved[host] += 1
                if resolved[host] > self.cap(host):
                    self.stopped[host] = f'{host} reached the request cap {self.cap(host)}'
                    raise Refused(self.stopped[host])
                if resolved[host] > self.requests[host]:  # a connection no HTTP hook saw: count it here
                    self.requests[host] = resolved[host]
            return resolve(host, *args, **kwargs)
        socket.getaddrinfo = getaddrinfo
        import requests.adapters
        send = requests.adapters.HTTPAdapter.send

        def checked(adapter, request, *args, **kwargs):
            self.before(request.url)
            response = send(adapter, request, *args, **kwargs)
            self.after(response.status_code, request.url)
            return response
        requests.adapters.HTTPAdapter.send = checked
        import urllib.error
        import urllib.request
        open_url = urllib.request.OpenerDirector.open

        def checked_urllib(opener, request, *args, **kwargs):
            url = request if isinstance(request, str) else request.full_url
            self.before(url)
            try:
                response = open_url(opener, request, *args, **kwargs)
            except urllib.error.HTTPError as exc:
                self.after(exc.code, url)
                raise
            self.after(response.status, url)
            return response
        urllib.request.OpenerDirector.open = checked_urllib
        try:
            from curl_cffi import requests as curl
        except ImportError:
            return
        request = curl.Session.request

        def checked_curl(session, method, url, *args, **kwargs):
            self.before(url)
            response = request(session, method, url, *args, **kwargs)
            self.after(response.status_code, url)
            return response
        curl.Session.request = checked_curl


class Run:
    """The private SQLite file of one run, with per-source checkpoints."""

    def __init__(self, pg, tables, since=None):
        from pipeline import postgres_isolated_collect as iso
        from pipeline.postgres_id_bands import band
        self.tables = tables
        self.path = Path(tempfile.mkdtemp(prefix='isolated-')) / 'run.db'
        with sqlite3.connect(self.path) as conn:
            self.seeded = iso.seed(pg, conn, tables, since)
            iso.seed_job_runs(pg, conn)  # a legacy script's own job record lands here
            band(conn)  # new rows of an id table take the candidate's band (pipeline.postgres_id_bands)
            self.before = {t: iso.rows_by_key(conn, t) for t in tables}

    def connect(self):
        projection = Path('/projection') / json.loads(Path('/projection/current.json').read_text())['file']
        conn = sqlite3.connect(f'file:{self.path}', uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=30000')
        # Unqualified names resolve to this file's tables first, then the projection's, which cannot be written.
        conn.execute('ATTACH DATABASE ? AS projection', (f'file:{projection}?mode=ro&immutable=1',))
        return conn

    def point_legacy_here(self):
        import config
        import database
        config.DB_PATH = database.DB_PATH = self.path
        database.get_connection = self.connect

    def checkpoint(self):
        with sqlite3.connect(self.path) as conn:
            for t in self.tables:
                conn.execute(f'DROP TABLE IF EXISTS "_checkpoint_{t}"')
                conn.execute(f'CREATE TABLE "_checkpoint_{t}" AS SELECT * FROM "{t}"')

    def rollback(self):
        with sqlite3.connect(self.path) as conn:
            for t in self.tables:
                conn.execute(f'DELETE FROM "{t}"')
                conn.execute(f'INSERT INTO "{t}" SELECT * FROM "_checkpoint_{t}"')

    def count(self, table, at='main'):
        with sqlite3.connect(self.path) as conn:
            return conn.execute(f'SELECT count(*) FROM "{"_checkpoint_" + table if at == "checkpoint" else table}"').fetchone()[0]

    def job_records(self):
        """The job records this run's legacy code wrote (the isolated id band)."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute('SELECT * FROM job_runs ORDER BY id')]

    def changes(self):
        from pipeline import postgres_isolated_collect as iso
        with sqlite3.connect(self.path) as conn:
            return {t: iso.delta(self.before[t], iso.rows_by_key(conn, t)) for t in self.tables}


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())


def _since_days(at):
    return (datetime.now(timezone.utc) - datetime.strptime(at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)).days


# ---------- sources: name → callable(run, previous state) returning (status, detail, gaps) ----------

def extseries_sources(network):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_ext_series import SOURCES

    def source(name):
        def call(_run, previous):
            module = importlib.import_module(f'pipeline.{name}')
            long_failing = bool(previous.get('failing_since')) and _since_days(previous['failing_since']) >= BACKFILL_AFTER_DAYS
            kwargs = {'backfill': True} if long_failing and 'backfill' in inspect.signature(module.collect).parameters else {}
            result = module.collect(**kwargs)
            status = result.get('status')
            detail = {k: result.get(k) for k in ('stored', 'latest', 'missing', 'error') if result.get(k)}
            if kwargs:
                detail['backfill'] = True
            if status == 'error':
                raise RuntimeError(result.get('error') or 'source reported an error')
            return ('partial' if status == 'partial' else 'ok'), detail, list(result.get('missing') or [])

        def pending(run):
            """What a failed source leaves unfilled: each of its series after its last stored month."""
            label = getattr(importlib.import_module(f'pipeline.{name}'), 'SOURCE', None)
            if not label:
                return []
            with sqlite3.connect(run.path) as conn:
                return [f'{series} after {last}' for series, last in conn.execute(
                    'SELECT series, max(period) FROM ext_series WHERE source LIKE ? GROUP BY series', (label + '%',))]
        call.pending = pending
        return call
    return [(name, source(name)) for name in SOURCES]


def _tail_days(conn, symbols, minimum):
    """Days to read back so that every ticker with history continues from its last stored close (a gap after a
    failed day or a restart is filled, not skipped)."""
    marks = ','.join('?' * len(symbols))
    last = [d for (d,) in conn.execute(f'SELECT max(trade_date) FROM sector_benchmark_prices WHERE ticker IN ({marks}) '
                                       'GROUP BY ticker HAVING count(*) >= 200', symbols)]
    if not last:
        return minimum
    return max(minimum, (date.today() - date.fromisoformat(min(last))).days + 5)


def sectorbench_sources(network):
    from pipeline import sector_benchmarks as sb
    from pipeline import us_sectors as us

    def kr_etfs(run, _previous):
        conn = run.connect()
        try:
            tickers = [r[0] for r in conn.execute('SELECT DISTINCT ticker FROM sector_benchmarks WHERE ticker IS NOT NULL')]
            sb.TAIL_DAYS = _tail_days(conn, tickers + [sb.KOSPI], 10)
            result = sb.collect(conn)
        finally:
            conn.close()
        if not result['tickers']:
            raise RuntimeError('no ETF close: ' + ', '.join(result['degraded'])[:200])
        return ('partial' if result['degraded'] else 'ok'), {'rows': result['rows'], 'tail_days': sb.TAIL_DAYS}, result['degraded']

    def kr_index(run, _previous):
        before_rows = run.count('sector_index', 'checkpoint')
        with run.connect() as conn:
            before_sectors = conn.execute('SELECT count(DISTINCT sector) FROM "_checkpoint_sector_index"').fetchone()[0]
            result = sb.compute_index(conn)
        if result['rows'] == 0 or result['sectors'] < before_sectors or result['rows'] < INDEX_KEEP * before_rows:
            raise RuntimeError(f"index incomplete ({result['sectors']} sectors, {result['rows']} rows; "
                               f"last good {before_sectors} sectors, {before_rows} rows): last good kept")
        return 'ok', result, []

    def us_etfs(run, _previous):
        conn = run.connect()
        try:
            us.TAIL_DAYS = _tail_days(conn, us.TICKERS + [us.SPY], 10)
            result = us.collect_etfs(conn)
        finally:
            conn.close()
        if not result['tickers']:
            raise RuntimeError('no US ETF close: ' + ', '.join(result['degraded'])[:200])
        return ('partial' if result['degraded'] else 'ok'), {'rows': result['rows'], 'tail_days': us.TAIL_DAYS}, result['degraded']

    def us_sector_info(run, _previous):
        conn = run.connect()
        try:
            result = us.collect_sectors(conn)
        finally:
            conn.close()
        if result['due'] and not result['fetched']:
            raise RuntimeError('no sector info: ' + ', '.join(result['failed'])[:200])
        return ('partial' if result['failed'] else 'ok'), {'due': result['due'], 'fetched': result['fetched']}, result['failed']

    return [('kr_etfs', kr_etfs), ('kr_index', kr_index), ('us_etfs', us_etfs), ('us_sector_info', us_sector_info)]


# Parts of the legacy job not moved: their table is published whole from the shared collector file by other jobs.
# ---------- prices: KRX daily closes by stock and date ----------

PRICE_WINDOW_DAYS = 45   # rows seeded, compared and mirrored (the gap window and the previous close fit in it)
PRICE_GAP_DAYS = 10      # the legacy daily repair window
PRICE_GIVE_UP = 5        # a stock and date Yahoo never has after this many tries no longer makes the run partial
PRICE_LIMIT = 0.30       # KRX daily price limit (a listing day has no previous close and is not checked)


def _kst_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Asia/Seoul'))


def price_window_start():
    return (_kst_now().date() - timedelta(days=PRICE_WINDOW_DAYS)).isoformat()


def closed_through(now=None):
    """The last KST day whose regular-session close is final (15:30 close, 10 minutes' margin)."""
    now = now or _kst_now()
    return (now.date() if (now.hour, now.minute) >= (15, 40) else now.date() - timedelta(days=1)).isoformat()


def price_gaps(conn, today=None):
    """{stock: [missing dates]} over the last PRICE_GAP_DAYS trading days (KOSPI calendar) for stocks quoted in the last
    30 days: the legacy daily repair's own selection."""
    today = today or _kst_now().date()
    since = (today - timedelta(days=PRICE_GAP_DAYS)).isoformat()
    days = [r[0] for r in conn.execute("SELECT DISTINCT snapshot_date FROM market_indicators WHERE indicator='index_kospi' "
                                       'AND snapshot_date >= ? AND snapshot_date < ?', (since, today.isoformat()))]
    have = {(c, d) for c, d in conn.execute('SELECT stock_code, trade_date FROM stock_prices WHERE trade_date >= ?', (since,))}
    active = {r[0] for r in conn.execute('SELECT DISTINCT stock_code FROM stock_prices WHERE trade_date >= ?',
                                         ((today - timedelta(days=30)).isoformat(),))}
    out = {}
    for code in sorted(active):
        missing = [d for d in sorted(days) if (code, d) not in have]
        if missing:
            out[code] = missing
    return out


def validate_prices(conn, rows, through=None):
    """(rows to publish, rejected [(stock, date, reason)]): a close is published only when it is final, positive,
    inside its own day's range and within the daily limit of the previous stored close."""
    through = through or closed_through()
    previous = {}
    for code, day, close in conn.execute('SELECT stock_code, trade_date, close FROM stock_prices ORDER BY stock_code, trade_date'):
        previous.setdefault(code, []).append((day, close))
    kept, rejected = [], []
    for row in rows:
        code, day, close = row['stock_code'], row['trade_date'], row['close']
        o, h, low = row.get('open'), row.get('high'), row.get('low')
        prior = [c for d, c in previous.get(code, []) if d < day and c]
        reason = None
        if day > through:
            reason = 'not closed yet'
        elif date.fromisoformat(day).weekday() >= 5:
            reason = 'weekend'
        elif not close or close <= 0:
            reason = 'no close'
        elif h is not None and low is not None and not (low <= close <= h and (o is None or low <= o <= h)):
            reason = 'outside its day range'
        elif prior and abs(close / prior[-1] - 1) > PRICE_LIMIT + 0.005:
            reason = f'{close / prior[-1] - 1:+.1%} vs previous close'
        elif row.get('volume') is not None and row['volume'] < 0:
            reason = 'negative volume'
        if reason:
            rejected.append((code, day, reason))
        else:
            kept.append(row)
    return kept, rejected


CORPORATE_ACTION = re.compile('병합|분할|증자|감자|합병|변경상장|추가상장|재상장|매매거래정지해제|권리락|액면')
CORPORATE_ACTION_DAYS = 45


def krx_tick(price):
    """KRX quotation unit (KOSPI and KOSDAQ alike since 2023-01-25)."""
    for upper, tick in ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500)):
        if price < upper:
            return tick
    return 1_000


def krx_limits(base, listing=False):
    """(lower, upper) daily price limits from the base price: ±30%, rounded inward to the quotation unit. On a
    stock's first trading day the base is the offering price and the range is 60%-400% of it."""
    import math
    high, low = (base * 4, base * 0.6) if listing else (base * (1 + PRICE_LIMIT), base * (1 - PRICE_LIMIT))
    return math.ceil(low / krx_tick(low)) * krx_tick(low), math.floor(high / krx_tick(high)) * krx_tick(high)


def previous_listing(day, lookback=7):
    """(day, {code: market}) of the latest earlier weekday KRX lists stocks for, or (None, None)."""
    d = date.fromisoformat(day)
    for _ in range(lookback):
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        time.sleep(KRX_PAUSE)
        listing = krx_listing(d.isoformat())
        codes = {r['ISU_SRT_CD']: market for market, records in listing.items() for r in records}
        if codes:
            return d.isoformat(), codes
    return None, None


def confirm_listing_days(rows, rejected, bases, markets=None):
    """Of the KRX bars rejected for the ±30% limits, the ones on the stock's first trading day in its market (KRX did not
    list it on the previous trading day, or listed it in another market: a transfer such as KONEX to KOSDAQ) inside the
    listing-day range of 60%-400% of the base. `markets` = {(code, day): market}. (confirmed rows, still rejected,
    evidence)."""
    by_key = {(r['stock_code'], r['trade_date']): r for r in rows}
    confirmed, still, evidence, before = [], [], {}, {}
    for code, day, reason in rejected:
        if not reason.startswith('outside the limits'):
            still.append((code, day, reason))
            continue
        try:
            if day not in before:
                before[day] = previous_listing(day)
        except Exception as exc:  # noqa: BLE001 - not confirmed this run
            still.append((code, day, f'{reason}; previous listing unavailable ({type(exc).__name__})'))
            continue
        previous_day, listed = before[day]
        row, base = by_key[(code, day)], bases.get((code, day))
        market = (markets or {}).get((code, day))
        if listed is None or (code in listed and (market is None or listed[code] == market)):
            still.append((code, day, reason + ('' if listed is None else f'; listed on {previous_day}, not a listing day')))
            continue
        lower, upper = krx_limits(base, listing=True)
        if lower <= row['close'] <= upper and lower <= row['high'] <= upper and lower <= row['low'] <= upper:
            confirmed.append(row)
            evidence[f'{code} {day}'] = {'listing_day': True, 'previous_day': previous_day,
                                         'previous_market': listed.get(code), 'market': market,
                                         'offering_base': base, 'limits': [lower, upper]}
        else:
            still.append((code, day, f'{reason}; listing day but outside {lower}-{upper}'))
    return confirmed, still, evidence


def krx_day(code, day):
    """KRX's own regular-session row of `code` on `day` and the day before: {close, change, base, kind, previous} or
    None. Needs the KRX data system login (KRX_ID/KRX_PW, as the retail job)."""
    from pykrx.website.krx.market import core
    from pykrx.website.krx.market.ticker import get_stock_ticker_isin
    start = (date.fromisoformat(day) - timedelta(days=10)).strftime('%Y%m%d')
    rows = core.개별종목시세().fetch(start, day.replace('-', ''), get_stock_ticker_isin(code), 1).to_dict('records')
    number = lambda v: int(str(v).replace(',', ''))  # noqa: E731
    by_day = {r['TRD_DD'].replace('/', '-'): r for r in rows}
    row = by_day.get(day)
    if not row:
        return None
    earlier = sorted(d for d in by_day if d < day)
    close, change = number(row['TDD_CLSPRC']), number(row['CMPPREVDD_PRC'])
    return {'close': close, 'change': change, 'base': close - change, 'kind': row['FLUC_TP_CD'],
            'previous': number(by_day[earlier[-1]]['TDD_CLSPRC']) if earlier else None}


def corporate_actions(code, day, conn):
    """DART disclosures of a corporate action that resets the base price, in the CORPORATE_ACTION_DAYS before `day`."""
    import requests
    found = conn.execute('SELECT corp_code FROM companies WHERE stock_code=?', (code,)).fetchone()
    key = os.environ.get('DART_API_KEY')
    if not found or not found[0] or not key:
        return []
    start = (date.fromisoformat(day) - timedelta(days=CORPORATE_ACTION_DAYS)).strftime('%Y%m%d')
    response = requests.get('https://opendart.fss.or.kr/api/list.json', timeout=20, params={
        'crtfc_key': key, 'corp_code': found[0], 'bgn_de': start, 'end_de': day.replace('-', ''), 'page_count': 100})
    response.raise_for_status()
    return [f"{x['rcept_dt']} {x['report_nm'].strip()}" for x in response.json().get('list') or []
            if CORPORATE_ACTION.search(x['report_nm'])]


def confirm_beyond_limit(conn, rejected, rows):
    """Of the closes rejected only for the daily limit against the stored previous close: the ones KRX confirms are
    published. The collected close must equal KRX's regular-session close and lie within that day's limits from KRX's
    base price; a DART corporate action is kept as supporting evidence for a base price that moved, not required.
    A close that differs from KRX (another session's price), or that KRX cannot confirm, stays for review.
    Returns (confirmed rows, still rejected, evidence)."""
    by_key = {(r['stock_code'], r['trade_date']): r for r in rows}
    confirmed, still, evidence = [], [], {}
    for code, day, reason in rejected:
        if 'vs previous close' not in reason:
            still.append((code, day, reason))
            continue
        row = by_key[(code, day)]
        try:
            krx = krx_day(code, day)
        except Exception as exc:  # noqa: BLE001 - not confirmed this run; tried again on the next
            still.append((code, day, f'{reason}; KRX value unavailable ({type(exc).__name__})'))
            continue
        if krx is None:
            still.append((code, day, f'{reason}; KRX has no row for the day'))
            continue
        if krx['close'] != row['close']:
            still.append((code, day, f"{reason}; collected {row['close']:g} ≠ KRX regular close {krx['close']:g}"))
            continue
        lower, upper = krx_limits(krx['base'])
        if not lower <= row['close'] <= upper:
            still.append((code, day, f"{reason}; outside KRX limits {lower}–{upper} (base {krx['base']})"))
            continue
        stored = conn.execute('SELECT close FROM stock_prices WHERE stock_code=? AND trade_date<? ORDER BY trade_date DESC LIMIT 1',
                              (code, day)).fetchone()
        try:
            actions = corporate_actions(code, day, conn) if krx['previous'] != krx['base'] else []
        except Exception:  # noqa: BLE001 - supporting evidence only
            actions = []
        confirmed.append(row)
        evidence[f'{code} {day}'] = {'krx_close': krx['close'], 'base': krx['base'], 'limits': [lower, upper],
                                     'krx_previous_close': krx['previous'], 'stored_previous_close': stored[0] if stored else None,
                                     **({'corporate_actions': actions[:3]} if actions else {})}
    return confirmed, still, evidence


# From this day the daily bars come from KRX's own market-wide prices (regular session: open, high, low, close
# together). Earlier days keep what was collected until they are corrected day by day, separately.
PRICE_KRX_FROM = os.environ.get('PRICE_KRX_FROM', '2026-11-23')
KRX_MARKETS = ('STK', 'KSQ', 'KNX')  # KOSPI, KOSDAQ, KONEX
KRX_SOURCE = 'krx:전종목시세(MDCSTAT01501)'
KRX_LOOKBACK_DAYS = 20     # missing days are tried again within this window
KRX_DAYS_PER_RUN = 5       # oldest first; the rest wait for the next run (a full lookback clears in two days)
KRX_PAUSE = float(os.environ.get('KRX_PAUSE', '3'))  # seconds between KRX requests
KRX_EMPTY_IS_HOLIDAY = 3   # a weekday KRX still has no prices for after this many days was not a trading day


def _krx_number(value):
    text = str(value).replace(',', '').strip()
    return int(float(text)) if text not in ('', '-') else None


# Jobs whose every changed row is logged with its previous value and source (collected_row_history).
HISTORY_SOURCE = {'prices': KRX_SOURCE, 'pricefix': 'krx-correction:전종목시세(MDCSTAT01501)',
                  'pricefactors': 'krx:전종목시세 base vs previous close'}


# A failed KRX login is remembered on the shared volume (/trial, every job's) and no job logs in again until an operator
# removes the mark: repeated failed logins can lock the account or get the address blocked (retail and prices share it).
KRX_COOLDOWN = Path(os.environ.get('KRX_LOGIN_COOLDOWN', '/trial/krx-login-hold'))


class KrxUnavailable(RuntimeError):
    """KRX's data system refused the login: no job logs in or requests anything until the hold is removed."""


def krx_login():
    """The KRX session, or KrxUnavailable (a failed login leaves the hold mark)."""
    if KRX_COOLDOWN.exists():
        raise KrxUnavailable(f'KRX login held since {KRX_COOLDOWN.read_text().strip()}; an operator removes {KRX_COOLDOWN}')
    if not os.environ.get('KRX_ID') or not os.environ.get('KRX_PW'):  # the scheduler withholds it while held
        raise KrxUnavailable('no KRX account in this run (held by the operator)')
    try:
        from pykrx.website.comm import auth  # importing pykrx logs in with KRX_ID/KRX_PW
        logged_in = auth._auth_session is not None
    except Exception as exc:  # noqa: BLE001 - a login page instead of JSON, a network error
        logged_in, reason = False, f'{type(exc).__name__}: {str(exc)[:80]}'
    else:
        reason = 'no session'
    if not logged_in:
        try:
            KRX_COOLDOWN.write_text(f'{_now()} UTC ({reason})')
        except OSError:
            pass
        raise KrxUnavailable(f'KRX login failed ({reason})')


def krx_listing(day):
    """{market: KRX market-wide records of `day`} for KOSPI, KOSDAQ and KONEX, every listed stock (traded or not)."""
    krx_login()
    from pykrx.website.krx.market import core
    listing = {}
    for market in KRX_MARKETS:
        if listing:
            time.sleep(KRX_PAUSE)
        listing[market] = core.전종목시세().fetch(day.replace('-', ''), market).to_dict('records')
    return listing


def krx_bar(r, day):
    """(regular-session bar, base price) of one KRX record, or (None, None) when the stock did not trade."""
    close, volume = _krx_number(r['TDD_CLSPRC']), _krx_number(r['ACC_TRDVOL'])
    if not close or not volume:
        return None, None
    return ({'stock_code': r['ISU_SRT_CD'], 'trade_date': day, 'open': _krx_number(r['TDD_OPNPRC']),
             'high': _krx_number(r['TDD_HGPRC']), 'low': _krx_number(r['TDD_LWPRC']), 'close': close, 'volume': volume,
             'market_cap': _krx_number(r['MKTCAP']), 'shares': _krx_number(r['LIST_SHRS'])},
            close - (_krx_number(r['CMPPREVDD_PRC']) or 0))


def krx_market_day(day):
    """KRX's regular-session bars of every listed stock on `day`: (rows, {stock: base price}, {stock: market}). A stock
    that did not trade (no volume) has no row, as before."""
    rows, bases, markets = [], {}, {}
    for market, records in krx_listing(day).items():
        for r in records:
            bar, base = krx_bar(r, day)
            if bar:
                rows.append(bar)
                bases[bar['stock_code']] = base
                markets[bar['stock_code']] = market
    return rows, bases, markets


UPSERT_BAR = ('INSERT INTO main.stock_prices (stock_code, trade_date, open, high, low, close, volume, market_cap, shares, '
              "fetched_at) VALUES (:stock_code,:trade_date,:open,:high,:low,:close,:volume,:market_cap,:shares,datetime('now')) "
              'ON CONFLICT(stock_code, trade_date) DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low, '
              'close=excluded.close, volume=excluded.volume, market_cap=excluded.market_cap, shares=excluded.shares, '
              'fetched_at=excluded.fetched_at '
              # only a bar whose values differ is rewritten: a repeat is no change (and leaves no history)
              'WHERE (open, high, low, close, volume, market_cap, shares) IS NOT '
              '(excluded.open, excluded.high, excluded.low, excluded.close, excluded.volume, excluded.market_cap, excluded.shares)')


def krx_days(prior_days, through, today=None, start=PRICE_KRX_FROM):
    """Weekdays from `start` (within the lookback) through `through` not yet collected or found closed."""
    today = today or _kst_now().date()
    first = max(date.fromisoformat(start), today - timedelta(days=KRX_LOOKBACK_DAYS))
    days, d = [], first
    while d.isoformat() <= through:
        if d.weekday() < 5 and prior_days.get(d.isoformat(), {}).get('status') not in ('done', 'closed'):
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def validate_krx(rows, bases):
    """(rows to publish, rejected): KRX bars are taken as they are when consistent within the day and inside that
    day's limits from KRX's own base price."""
    kept, rejected = [], []
    for row in rows:
        o, h, low, c = row['open'], row['high'], row['low'], row['close']
        base = bases.get((row['stock_code'], row['trade_date']))
        reason = None
        if not (low and h and o and low <= min(o, c) and max(o, c) <= h):
            reason = 'open/close outside the day range'
        elif base and base > 0 and not krx_limits(base)[0] <= c <= krx_limits(base)[1]:
            reason = f'outside the limits of base {base}'
        if reason:
            rejected.append((row['stock_code'], row['trade_date'], reason))
        else:
            kept.append(row)
    return kept, rejected


def adjustment(code, day, base, previous_close):
    """(stock_code, ex_date, factor, base, previous_close) when KRX's base price is not the previous close (a corporate
    action reset it), else None. factor = base / previous close."""
    if not base or not previous_close or base == previous_close:
        return None
    return code, day, base / previous_close, base, previous_close


# ---------- pricefactors: past adjustment factors and the raw-vs-stored comparison (run by hand, in batches) ----------

PRICEFACTORS_FROM = '2021-07-12'   # the first stored daily bar
PRICEFACTORS_SOURCE = 'krx:전종목시세 base vs previous close'


def pricefactors_sources(network, pg):
    """Walk KRX's market-wide prices day by day from where the last run stopped (or PRICEFACTORS_FROM) to
    PRICEFACTORS_TO, recording a factor wherever KRX's base price is not its own previous close, and counting per day
    how the stored bars differ from KRX's raw regular-session bars (nothing is changed). Stops at the request cap and
    leaves where it stopped for the next run."""
    adjustments = []

    def sweep(_run, prior):
        # Progress lives in collect_source_state (job pricefactors, source krx_sweep), gaps_json:
        # [{'last_done': the last day walked, 'next_day': where the next run starts, 'previous_closes': its closes}].
        # PRICEFACTORS_FROM overrides where to start (the first run, or a deliberate restart).
        progress = next((g for g in prior.get('gaps') or [] if isinstance(g, dict) and 'next_day' in g), {})
        finished = next((g for g in prior.get('gaps') or [] if isinstance(g, dict) and g.get('done')), None)
        if finished and not os.environ.get('PRICEFACTORS_FROM'):
            return 'ok', {'done': True, 'until': finished.get('last_done')}, [finished]
        start = os.environ.get('PRICEFACTORS_FROM') or progress.get('next_day') or PRICEFACTORS_FROM
        day = date.fromisoformat(start)
        last = date.fromisoformat(os.environ.get('PRICEFACTORS_TO') or '2026-11-20')
        pause = float(os.environ.get('PRICEFACTORS_PAUSE', '2'))
        previous = progress.get('previous_closes') if start == progress.get('next_day') else None
        last_done = progress.get('last_done') if start == progress.get('next_day') else None
        stats, stop_reason = {}, None

        def kept(reason):  # stop without losing the place
            return 'error', {'error': reason, 'until': last_done}, [{'last_done': last_done, 'next_day': day.isoformat(),
                                                                       'previous_closes': previous}]
        if previous is None:  # the trading day before the first: its closes are the first day's previous closes
            try:
                prev_day, _ = previous_listing(day.isoformat())
                previous = ({r['ISU_SRT_CD']: _krx_number(r['TDD_CLSPRC']) for recs in krx_listing(prev_day).values()
                             for r in recs} if prev_day else {})
            except Exception as exc:  # noqa: BLE001
                return kept(f'{type(exc).__name__}: {str(exc)[:120]}')
        while day <= last:
            if day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            try:
                listing = krx_listing(day.isoformat())
            except Exception as exc:  # noqa: BLE001 - a refusal or an expired KRX session (a login page, not JSON):
                stop_reason = f'{type(exc).__name__}: {str(exc)[:120]}'  # stop here; the next run logs in again
                break
            if any(host.endswith('krx.co.kr') for host in network.stopped):
                break  # the library may swallow the refusal and return nothing: not a holiday, the same day next run
            closes, traded = {}, {}
            for records in listing.values():
                for r in records:
                    code, close = r['ISU_SRT_CD'], _krx_number(r['TDD_CLSPRC'])
                    closes[code] = close
                    bar, base = krx_bar(r, day.isoformat())
                    if bar:
                        traded[code] = bar
                        found = adjustment(code, day.isoformat(), base, (previous or {}).get(code))
                        if found:
                            adjustments.append(found)
            if closes:
                stored = {row['stock_code']: row for (row,) in pg.execute(
                    "SELECT row_data FROM legacy_supplement_rows WHERE table_name='stock_prices' AND row_data->>'trade_date'=%s",
                    (day.isoformat(),))}
                year = stats.setdefault(day.isoformat()[:7], Counter())
                year['days'] += 1
                year['stored'] += len(stored)
                year['close_differs'] += sum(1 for c, row in stored.items() if c in traded and row.get('close') != traded[c]['close'])
                year['not_traded'] += sum(1 for c in stored if c not in traded and c in closes)
                year['not_listed'] += sum(1 for c in stored if c not in closes)
                year['missing'] += sum(1 for c in traded if c not in stored)
                previous = closes
                last_done = day.isoformat()
                time.sleep(pause)
            day += timedelta(days=1)
        done = day > last
        if not last_done and stop_reason:
            return kept(stop_reason)
        detail = {'until': last_done, 'next_day': day.isoformat(), 'done': done, 'factors': len(adjustments),
                  'by_month': {m: dict(c) for m, c in stats.items()}, **({'stopped': stop_reason} if stop_reason else {})}
        gaps = [{'last_done': last_done, 'done': True}] if done else [
            {'last_done': last_done, 'next_day': day.isoformat(), 'previous_closes': previous}]
        return ('ok' if done else 'partial'), detail, gaps
    sweep.adjustments = adjustments
    return [('krx_sweep', sweep)]


def prices_sources(network):
    bases, markets, adjustments = {}, {}, []

    def krx_daily(run, prior):
        prior_days = {g['day']: g for g in prior.get('gaps') or [] if isinstance(g, dict) and 'day' in g}
        today = _kst_now().date()
        todo = krx_days(prior_days, closed_through())
        # a few days per run; after the first failed lookup nothing more is asked of KRX this run
        todo, deferred = todo[:KRX_DAYS_PER_RUN], todo[KRX_DAYS_PER_RUN:]
        state = dict(prior_days)
        collected, missing = {}, []
        for i, day in enumerate(todo):
            entry = {'day': day, 'tries': prior_days.get(day, {}).get('tries', 0) + 1}
            if i:
                time.sleep(KRX_PAUSE)
            try:
                rows, day_bases, day_markets = krx_market_day(day)
            except Exception as exc:  # noqa: BLE001 - recorded as missing; never filled from another source
                state[day] = {**entry, 'status': 'missing', 'reason': f'{type(exc).__name__}: {str(exc)[:80]}'}
                missing.append(day)
                deferred = todo[i + 1:] + deferred
                break
            if not rows:
                old = (today - date.fromisoformat(day)).days > KRX_EMPTY_IS_HOLIDAY
                state[day] = {**entry, 'status': 'closed' if old else 'missing', 'reason': 'KRX has no prices'}
                if not old:
                    missing.append(day)
                continue
            with run.connect() as conn:
                conn.executemany(UPSERT_BAR, rows)
            with run.connect() as conn:
                for code, base in day_bases.items():
                    prev = conn.execute('SELECT close FROM main.stock_prices WHERE stock_code=? AND trade_date<? '
                                        'ORDER BY trade_date DESC LIMIT 1', (code, day)).fetchone()
                    found = adjustment(code, day, base, prev[0] if prev else None)
                    if found:
                        adjustments.append(found)
            bases.update({(code, day): base for code, base in day_bases.items()})
            markets.update({(code, day): market for code, market in day_markets.items()})
            state[day] = {**entry, 'status': 'done', 'rows': len(rows)}
            collected[day] = len(rows)
        for day in deferred:  # not asked this run: still missing
            state.setdefault(day, {'day': day, 'tries': 0, 'status': 'missing', 'reason': 'deferred to a later run'})
        missing += deferred
        keep = sorted(state, reverse=True)[:30]
        gaps = [state[d] for d in sorted(keep)]
        detail = {'from': PRICE_KRX_FROM, 'collected': collected, 'missing': missing}
        if todo and not collected and missing:
            return 'error', {**detail, 'error': f'KRX prices missing for {", ".join(missing)}'}, gaps
        return ('partial' if missing else 'ok'), detail, gaps
    krx_daily.bases, krx_daily.markets, krx_daily.adjustments = bases, markets, adjustments
    return [('krx_daily', krx_daily)]


# ---------- pricefix: one past day corrected to KRX's regular session (run by hand, one day per run) ----------

PRICEFIX_SOURCE = 'krx-correction:전종목시세(MDCSTAT01501)'
KRX_MIN_LISTED = {'STK': 800, 'KSQ': 1500, 'KNX': 50}  # a day KRX lists fewer is not complete enough to correct from


def pricefix_sources(network):
    """PRICEFIX_DATE corrected from KRX's market-wide prices, once KRX's listing of the day is complete:
    a stock that traded gets KRX's regular-session bar (added when missing); a listed stock that did not trade has its
    row removed (no trading bar, so it leaves the bar and indicator aggregates); a stored row KRX does not list at all
    cannot be told apart from a source gap and is held unchanged."""
    day = os.environ['PRICEFIX_DATE']
    bases, markets = {}, {}

    def correct(run, _prior):
        listing = krx_listing(day)
        coverage = {market: len(records) for market, records in listing.items()}
        short = {m: n for m, n in coverage.items() if n < KRX_MIN_LISTED[m]}
        if short:
            return 'error', {'error': f'KRX listing incomplete {short}', 'coverage': coverage}, [{'day': day, 'status': 'coverage'}]
        traded, quiet = {}, set()
        for market, records in listing.items():
            for r in records:
                bar, base = krx_bar(r, day)
                if bar:
                    traded[bar['stock_code']] = bar
                    bases[(bar['stock_code'], day)] = base
                    markets[(bar['stock_code'], day)] = market
                else:
                    quiet.add(r['ISU_SRT_CD'])
        with run.connect() as conn:
            stored = {c for (c,) in conn.execute('SELECT stock_code FROM main.stock_prices WHERE trade_date=?', (day,))}
            conn.executemany(UPSERT_BAR, list(traded.values()))
            removed = sorted(stored & quiet)
            conn.executemany('DELETE FROM main.stock_prices WHERE stock_code=? AND trade_date=?', [(c, day) for c in removed])
        held = sorted(stored - set(traded) - quiet)
        detail = {'day': day, 'coverage': coverage, 'krx_traded': len(traded), 'krx_no_trade': len(quiet),
                  'stored': len(stored), 'added': len(set(traded) - stored), 'no_trade_removed': len(removed),
                  'held_not_listed': held}
        return ('partial' if held else 'ok'), detail, ([{'day': day, 'held_not_listed': held}] if held else [])
    correct.bases, correct.markets = bases, markets
    return [('krx_correction', correct)]


def mirror(pg, tables, since=None):
    """Make the shared collector file's copy of the owned `tables` equal PG's (a WINDOWS table from `since`), in one
    SQLite transaction, so the jobs still on that file read only published (validated) rows. {table: rows written}."""
    import refactor_collect_trial as trial
    from pipeline.postgres_isolated_collect import WINDOWS
    work = sqlite3.connect(trial.WORK, timeout=60)
    written = {}
    try:
        with work:
            for table in tables:
                columns = pg.execute('SELECT columns FROM legacy_supplement_tables WHERE table_name=%s', (table,)).fetchone()[0]
                window = f" AND row_data->>'{WINDOWS[table]}' >= %s" if table in WINDOWS else ''
                rows = [[row.get(c) for c in columns] for (row,) in pg.execute(
                    'SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s' + window,
                    (table, since) if window else (table,))]
                if window:
                    work.execute(f'DELETE FROM "{table}" WHERE "{WINDOWS[table]}" >= ?', (since,))
                else:
                    work.execute(f'DELETE FROM "{table}"')
                work.executemany(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})', rows)
                written[table] = len(rows)
    finally:
        work.close()
    return written


def mirror_keys(pg, table, rows, deleted):
    """The rows of a shared table this run published (and the keys it deleted) put into the shared collector file, so
    that file's jobs, which still replace the table whole, keep them."""
    import refactor_collect_trial as trial
    from pipeline.postgres_isolated_collect import key_of
    columns = pg.execute('SELECT columns FROM legacy_supplement_tables WHERE table_name=%s', (table,)).fetchone()[0]
    where = ' AND '.join(f'"{c}"=?' for c in key_of(table))
    work = sqlite3.connect(trial.WORK, timeout=60)
    try:
        with work:
            work.executemany(f'DELETE FROM "{table}" WHERE {where}', [tuple(k) for k in deleted])
            work.executemany(f'INSERT OR REPLACE INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                             [[row.get(c) for c in columns] for row in rows])
    finally:
        work.close()
    return len(rows) + len(deleted)


def mirror_high52w(pg, days):
    """The shared collector file's high_52w signals of `days` made equal to PG's (its other signals are its own jobs')."""
    import refactor_collect_trial as trial
    columns = pg.execute("SELECT columns FROM legacy_supplement_tables WHERE table_name='signals'").fetchone()[0]
    rows = [[row.get(c) for c in columns] for (row,) in pg.execute(
        "SELECT row_data FROM legacy_supplement_rows WHERE table_name='signals' AND row_data->>'signal_type'='high_52w' "
        "AND row_data->>'date' = ANY(%s)", (list(days),))]
    work = sqlite3.connect(trial.WORK, timeout=60)
    try:
        with work:
            work.executemany("DELETE FROM signals WHERE signal_type='high_52w' AND date=?", [(d,) for d in days])
            work.executemany(f'INSERT INTO signals ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})', rows)
    finally:
        work.close()
    return len(rows)


def legacy_sources(label):
    """The job's unchanged script as one source, on the private file; its own job record decides the outcome."""
    if KRX_COOLDOWN.exists():  # the retail job logs in to KRX on its own (pykrx): without the account it skips that part
        os.environ.pop('KRX_ID', None)
        os.environ.pop('KRX_PW', None)
    import database
    import refactor_collect_job as job
    import refactor_collect_trial as trial
    argv, record = job.job_argv(label)

    def script(run, _prior):
        database.init_db = lambda: None  # the private file has the owned tables; the rest is read from the projection
        started = _now()
        os.chdir('/app')
        refused = None
        if label in job.TABLE_MODEL_CAPS:  # model calls: recorded in llm_calls and capped per run, as on the shared path
            from pipeline import llm, postgres_llm_calls
            postgres_llm_calls.install(llm, trial._pg)
            refused = job._cap_table_model_calls(job.TABLE_MODEL_CAPS[label])
        try:
            trial._run_script(*argv)  # a non-zero exit raises HeldBack: the source fails and its writes are rolled back
        except trial.Aborted as exc:  # the cap's refusal (a BaseException): this source fails, the job still records
            raise RuntimeError(f'model call refused: {exc}') from None
        finally:
            if refused is not None:
                refused.restore()
        if refused:
            raise RuntimeError(f'model call cap {job.TABLE_MODEL_CAPS[label]} reached (a later call was refused)')
        if not record:
            return 'ok', {}, []
        with run.connect() as conn:
            found = conn.execute('SELECT status, summary FROM main.job_runs WHERE job=? AND ran_at>=? ORDER BY id DESC LIMIT 1',
                                 (record, started)).fetchone()
        if found is None or found[0] == 'error':
            raise RuntimeError(f"job record {record}: {found[1][:150] if found else 'missing'}")
        return ('partial' if found[0] == 'partial' else 'ok'), {'record': found[0], 'summary': (found[1] or '')[:200]}, []
    return [('script', script)]


NOT_MOVED = {'sectorbench': {'us_follow_prices': 'us_prices is still replaced whole by the shared-file jobs'}}


def run_sources(run, sources, previous, network=None):
    """Each source in turn; a failed one's writes are rolled back. Returns {source: state} and per-source details."""
    states, details = {}, {}
    now = _now()
    for name, call in sources:
        prior = previous.get(name, {})
        run.checkpoint()
        asked = Counter(network.requests) if network else Counter()
        try:
            status, detail, gaps = call(run, prior)
        except Exception as exc:  # noqa: BLE001 - a failed source is rolled back; the others go on
            run.rollback()
            # A collector often swallows the refused request and reports a bare error: name the stop it hit.
            stops = [network.stopped[h] for h in (network.requests - asked) if h in network.stopped] if network else []
            error = '; '.join([f'{type(exc).__name__}: {exc}', *stops])
            states[name] = {'status': 'error', 'last_ok_at': prior.get('last_ok_at'),
                            'failing_since': prior.get('failing_since') or now, 'last_error': error,
                            'attempts': prior.get('attempts', 0) + 1,
                            'gaps': (getattr(call, 'pending', None) or (lambda _r: []))(run) or prior.get('gaps') or ['all']}
            details[name] = {'error': error[:200]}
            continue
        if status == 'error':  # a source that failed without raising keeps the gaps it worked out (its days)
            run.rollback()
            states[name] = {'status': 'error', 'last_ok_at': prior.get('last_ok_at'),
                            'failing_since': prior.get('failing_since') or now, 'last_error': detail.get('error'),
                            'attempts': prior.get('attempts', 0) + 1, 'gaps': gaps}
            details[name] = detail
            continue
        states[name] = {'status': status, 'last_ok_at': now,
                        'failing_since': (prior.get('failing_since') or now) if status == 'partial' else None,
                        'last_error': None, 'attempts': prior.get('attempts', 0) + 1 if status == 'partial' else 0,
                        'gaps': [g if isinstance(g, dict) else str(g) for g in gaps][:2000]}
        details[name] = detail
    return states, details


def outcome_of(states, applied_counts):
    failed = sorted(n for n, s in states.items() if s['status'] == 'error')
    partial = sorted(n for n, s in states.items() if s['status'] == 'partial')
    done = ', '.join(f'{t} +{u}/-{d}' for t, (u, d) in applied_counts.items() if u or d) or 'no change'
    if failed and len(failed) == len(states):
        return f'failed: every source failed ({", ".join(failed)})'
    if failed or partial:
        return f'partial: {done}; failed {", ".join(failed) or "-"}; incomplete {", ".join(partial) or "-"}'
    return f'applied: {done}'


def settle(connect, label, token, started, outcome, exc, requests, result):
    """After a failed publication: (run id, outcome). Found by its token, it took effect; not found, nothing was
    published (one transaction) and the failure is recorded; PG unreachable, nobody can tell: held back."""
    from pipeline import postgres_collect_runs
    from pipeline import postgres_isolated_collect as iso
    try:
        pg = connect()
        run_id = iso.published(pg, label, token)
        if run_id is not None:
            return run_id, outcome
        outcome = f'failed: publication error {type(exc).__name__}: {str(exc)[:150]}'
        return postgres_collect_runs.record(pg, label, started, outcome, requests=requests, result=result), outcome
    except Exception:  # noqa: BLE001
        return None, 'held back: publication state unknown'


def run(label):
    if label == 'pricefactors':  # a sweep of past days is the bulk lookup KRX's terms forbid (KDM notice, 2026-11-21)
        raise SystemExit('pricefactors is not run over data.krx.co.kr: past factors need an official route (KRX Open API)')
    import refactor_collect_trial as trial
    from pipeline import postgres_isolated_collect as iso
    started = _now()
    pg = trial._pg()
    iso.initialize(pg)
    # ISOLATED_HOST_CAPS (JSON) narrows caps for a rehearsal of the stop rules; production uses CAPS.
    network = Network({**CAPS[label], **json.loads(os.environ.get('ISOLATED_HOST_CAPS') or '{}')})
    network.install()
    previous = iso.states(pg, label)
    tables = TABLES[label]
    since = price_window_start() if label == 'prices' else os.environ['PRICEFIX_DATE'] if label == 'pricefix' else None
    private = Run(pg, tables, since)
    private.point_legacy_here()
    sources = (legacy_sources(label) if label in LEGACY else
               {'extseries': extseries_sources, 'sectorbench': sectorbench_sources, 'prices': prices_sources,
                'pricefix': pricefix_sources}[label](network)) if label != 'pricefactors' else pricefactors_sources(network, pg)
    states, details = run_sources(private, sources, previous, network)
    changes = private.changes()
    if os.environ.get('ISOLATED_DRY_RUN') == '1':  # a rehearsal: what would be published, nothing published
        print(json.dumps({'label': label, 'dry_run': True, 'states': states, 'details': details,
                          'changes': {t: (len(r), len(d)) for t, (r, d) in changes.items()},
                          'requests_by_host': dict(network.requests), 'statuses': dict(network.statuses)},
                         ensure_ascii=False, default=str))
        return 'dry run'
    rejected, evidence = [], {}
    if label in ('prices', 'pricefix'):  # only consistent KRX bars are published; a rejected one stays as PG has it
        day_bases = sources[0][1].bases
        rows = changes['stock_prices'][0]
        kept, rejected = validate_krx(rows, day_bases)
        if rejected:
            confirmed, rejected, evidence = confirm_listing_days(rows, rejected, day_bases, sources[0][1].markets)
            kept += confirmed
        changes['stock_prices'] = (kept, changes['stock_prices'][1])
    signal_days = sorted({r['trade_date'] for r in changes['stock_prices'][0]}) if label == 'prices' else []
    high_52w = None
    if signal_days:  # the 52-week highs of the days published, published with them
        try:
            import refactor_recompute_high52w as high52w
            upserts, deletes, report = high52w.reconcile(pg, signal_days[0], signal_days[-1], signal_days,
                                                         overlay=changes['stock_prices'][0],
                                                         removed=changes['stock_prices'][1])
            changes['signals'] = (upserts, deletes)
            high_52w = {day: {k: len(v) if isinstance(v, list) else v for k, v in r.items()} for day, r in report.items()}
        except Exception as exc:  # noqa: BLE001 - the bars still go out; the run is partial
            signal_days, high_52w = [], {'error': f'{type(exc).__name__}: {str(exc)[:120]}'}
    shrunk = [t for t in tables if private.seeded[t] and private.count(t) < SHRINK_LIMIT * private.seeded[t]]
    counts = {t: (len(rows), len(gone)) for t, (rows, gone) in changes.items()}
    result = {'sources': details, 'not_moved': NOT_MOVED.get(label, {}), 'stopped': network.stopped,
              **({'rejected': len(rejected), 'rejected_sample': rejected[:20]} if rejected else {}),
              **({'confirmed_beyond_limit': evidence} if evidence else {}),
              **({'high_52w': high_52w} if high_52w else {})}
    token = uuid.uuid4().hex
    if shrunk:  # the private file lost most of a table: nothing is published and collection is held
        outcome = f'held back: {", ".join(shrunk)} shrank below half'
        changes = {}
    else:
        outcome = outcome_of(states, counts)
        if rejected and outcome.startswith('applied'):
            outcome = 'partial' + outcome[len('applied'):] + f'; rejected {len(rejected)} closes'
        if high_52w and 'error' in high_52w:
            outcome = ('partial' + outcome[len('applied'):] if outcome.startswith('applied') else outcome) + \
                '; 52-week highs not computed'
    requests = dict(network.requests)
    try:
        run_id, _ = iso.publish(pg, label, started, outcome, changes, states, token=token, requests=requests, result=result,
                                records=private.job_records(), history=HISTORY_SOURCE.get(label),
                                adjustments=getattr(sources[0][1], 'adjustments', ()))
    except Exception as exc:  # noqa: BLE001 - whether the commit took effect is settled from the run record
        run_id, outcome = settle(trial._pg, label, token, started, outcome, exc, requests, result)
    if run_id is not None and not outcome.startswith('held back'):
        try:
            result['mirrored'] = mirror(pg, [t for t in tables if t in iso.KEYS], since)
            for table in tables:
                if table in iso.SHARED_KEYS and table in changes:
                    result['mirrored'][table] = mirror_keys(pg, table, *changes[table])
            if signal_days:
                result['mirrored']['signals'] = mirror_high52w(pg, signal_days)
        except Exception as exc:  # noqa: BLE001 - the shared file's readers could see unpublished closes: hold all
            outcome = f'held back: published, but the shared file was not aligned ({type(exc).__name__})'
            from pipeline import postgres_collect_runs
            postgres_collect_runs.record(pg, label, started, outcome, requests=requests, result=result)
    print(json.dumps({'run': run_id, 'label': label, 'outcome': outcome, 'requests_by_host': requests,
                      'statuses': dict(network.statuses), 'model_calls': 0}, ensure_ascii=False))
    return outcome

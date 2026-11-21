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
          'twrevenue': ('tw_monthly_revenue',)}
JOBS = ('extseries', 'sectorbench', 'prices', *LEGACY)
# Requests per source host and run; a key starting with '.' covers every host under that domain.
CAPS = {'extseries': {'': 30},
        # Naver realtime quotes in batches of 200 codes (about 15), then Yahoo for the gaps of the last 10 days
        # (+ Naver daily prices and DART disclosures for the few closes beyond the daily limit)
        'prices': {'': 20, 'polling.finance.naver.com': 30, '.finance.yahoo.com': 300},
        # credit (macbook-source #3 6942831447): 34 companies' issuer scan, symbol search fallback, 10 FRED series
        'credit': {'': 20, 'scanner.tradingview.com': 150, 'symbol-search.tradingview.com': 60,
                   'data.tradingview.com': 150, 'fred.stlouisfed.org': 12},
        'retail': {'': 20}, 'twrevenue': {'': 20},
        # 14 KR ETFs + KOSPI one by one, the US ETF batch, then sector info of followed tickers due for refresh
        'sectorbench': {'': 20, '.yahoo.com': 120}}
TABLES = {**LEGACY, 'extseries': ('ext_series', 'expectation_claims'), 'prices': ('stock_prices',),
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


def naver_day(code, day):
    """(close, change against the exchange's base price) of `code` on `day` from Naver's daily prices, or None."""
    import requests
    response = requests.get(f'https://m.stock.naver.com/api/stock/{code}/price', params={'pageSize': 20, 'page': 1},
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
    response.raise_for_status()
    number = lambda v: float(str(v).replace(',', '')) if v not in (None, '') else None  # noqa: E731
    for item in response.json():
        if (item.get('localTradedAt') or '')[:10] == day:
            return number(item.get('closePrice')), number(item.get('compareToPreviousClosePrice'))
    return None


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
    """Of the closes rejected only for the daily limit against the stored previous close, the ones the exchange's own
    base price and a corporate action confirm: Naver has the same close within the limit of its base price, and DART
    has a disclosure that resets the base price (a consolidation, split, capital change, relisting). Returns
    (confirmed rows, still rejected, evidence)."""
    by_key = {(r['stock_code'], r['trade_date']): r for r in rows}
    confirmed, still, evidence = [], [], {}
    for code, day, reason in rejected:
        if 'vs previous close' not in reason:
            still.append((code, day, reason))
            continue
        try:
            quote = naver_day(code, day)
            actions = corporate_actions(code, day, conn) if quote else []
        except Exception as exc:  # noqa: BLE001 - not confirmed this run; tried again on the next
            still.append((code, day, f'{reason}; not confirmed ({type(exc).__name__})'))
            continue
        row = by_key[(code, day)]
        if quote and quote[0] == row['close'] and quote[1] is not None:
            base = quote[0] - quote[1]
            within = base > 0 and abs(quote[0] / base - 1) <= PRICE_LIMIT + 0.0005
            if within and actions:
                confirmed.append(row)
                evidence[f'{code} {day}'] = {'base': base, 'actions': actions[:3]}
                continue
            reason = f'{reason}; base {base:g}' + ('' if within else ' beyond limit') + ('' if actions else ', no corporate action')
        else:
            reason = f'{reason}; Naver daily close differs or missing'
        still.append((code, day, reason))
    return confirmed, still, evidence


def prices_sources(network):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ingest_prices as ip
    legacy_batch = ip._yf_batch
    attempted = set()

    def batch(yf, tickers, start, end, tries=4):
        # once a Yahoo host is stopped, the rest of the batches are not tried (and not waited for): they stay gaps
        if any(host.endswith('yahoo.com') for host in network.stopped):
            return None, set()
        attempted.update(t.split('.')[0] for t in tickers)
        return legacy_batch(yf, tickers, start, end, tries=1)  # a 429 stops the host here instead of a backoff
    ip._yf_batch = batch

    def naver_daily(run, _prior):
        ip.get_connection = run.connect
        result = ip.ingest_daily(repair_days=0)
        if result['status'] == 'error':
            raise RuntimeError(f"every Naver batch failed ({result['failed']} stocks)")
        return ('partial' if result['failed'] else 'ok'), {k: result[k] for k in ('upsert', 'days', 'changed', 'failed')}, []

    def yahoo_gaps(run, prior):
        ip.get_connection = run.connect
        tries = {g['code']: g.get('tries', 0) for g in prior.get('gaps') or [] if isinstance(g, dict)}
        with run.connect() as conn:
            gaps = price_gaps(conn)
        if not gaps:
            return 'ok', {'gaps': 0}, []
        order = sorted(gaps, key=lambda c: (tries.get(c, 0), c))  # least tried first: a dead code cannot starve the rest
        ip.repair(PRICE_GAP_DAYS, only_missing=True, codes=order)
        with run.connect() as conn:
            left = price_gaps(conn)
        state = [{'code': c, 'dates': d, 'tries': tries.get(c, 0) + (c in attempted)} for c, d in left.items()]
        open_gaps = [g for g in state if g['tries'] < PRICE_GIVE_UP]
        detail = {'gaps': len(gaps), 'filled': len(gaps) - len(left), 'left': len(left),
                  'given_up': len(state) - len(open_gaps)}
        return ('partial' if open_gaps else 'ok'), detail, state

    return [('naver_daily', naver_daily), ('yahoo_gaps', yahoo_gaps)]


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


def legacy_sources(label):
    """The job's unchanged script as one source, on the private file; its own job record decides the outcome."""
    import database
    import refactor_collect_job as job
    import refactor_collect_trial as trial
    argv, record = job.job_argv(label)

    def script(run, _prior):
        database.init_db = lambda: None  # the private file has the owned tables; the rest is read from the projection
        started = _now()
        os.chdir('/app')
        trial._run_script(*argv)  # a non-zero exit raises HeldBack: the source fails and its writes are rolled back
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
    since = price_window_start() if label == 'prices' else None
    private = Run(pg, tables, since)
    private.point_legacy_here()
    sources = (legacy_sources(label) if label in LEGACY else
               {'extseries': extseries_sources, 'sectorbench': sectorbench_sources, 'prices': prices_sources}[label](network))
    states, details = run_sources(private, sources, previous, network)
    changes = private.changes()
    rejected, evidence = [], {}
    if label == 'prices':  # only validated closes are published; a rejected stock and date stays as PG has it
        with private.connect() as conn:  # the projection's companies give DART corp codes
            kept, rejected = validate_prices(conn, changes['stock_prices'][0])
            confirmed, rejected, evidence = confirm_beyond_limit(conn, rejected, changes['stock_prices'][0])
        changes['stock_prices'] = (kept + confirmed, changes['stock_prices'][1])
    shrunk = [t for t in tables if private.seeded[t] and private.count(t) < SHRINK_LIMIT * private.seeded[t]]
    counts = {t: (len(rows), len(gone)) for t, (rows, gone) in changes.items()}
    result = {'sources': details, 'not_moved': NOT_MOVED.get(label, {}), 'stopped': network.stopped,
              **({'rejected': len(rejected), 'rejected_sample': rejected[:20]} if rejected else {}),
              **({'confirmed_beyond_limit': evidence} if evidence else {})}
    token = uuid.uuid4().hex
    if shrunk:  # the private file lost most of a table: nothing is published and collection is held
        outcome = f'held back: {", ".join(shrunk)} shrank below half'
        changes = {}
    else:
        outcome = outcome_of(states, counts)
        if rejected and outcome.startswith('applied'):
            outcome = 'partial' + outcome[len('applied'):] + f'; rejected {len(rejected)} closes'
    requests = dict(network.requests)
    try:
        run_id, _ = iso.publish(pg, label, started, outcome, changes, states, token=token, requests=requests, result=result,
                                records=private.job_records())
    except Exception as exc:  # noqa: BLE001 - whether the commit took effect is settled from the run record
        run_id, outcome = settle(trial._pg, label, token, started, outcome, exc, requests, result)
    if run_id is not None and not outcome.startswith('held back'):
        try:
            result['mirrored'] = mirror(pg, tables, since)
        except Exception as exc:  # noqa: BLE001 - the shared file's readers could see unpublished closes: hold all
            outcome = f'held back: published, but the shared file was not aligned ({type(exc).__name__})'
            from pipeline import postgres_collect_runs
            postgres_collect_runs.record(pg, label, started, outcome, requests=requests, result=result)
    print(json.dumps({'run': run_id, 'label': label, 'outcome': outcome, 'requests_by_host': requests,
                      'statuses': dict(network.statuses), 'model_calls': 0}, ensure_ascii=False))
    return outcome

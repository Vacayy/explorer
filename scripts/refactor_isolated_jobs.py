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

JOBS = ('extseries', 'sectorbench')
# Requests per source host and run; a key starting with '.' covers every host under that domain.
CAPS = {'extseries': {'': 30},
        # 14 KR ETFs + KOSPI one by one, the US ETF batch, then sector info of followed tickers due for refresh
        'sectorbench': {'': 20, '.yahoo.com': 120}}
TABLES = {'extseries': ('ext_series', 'expectation_claims'),
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

    def __init__(self, pg, tables):
        from pipeline import postgres_isolated_collect as iso
        from pipeline.postgres_id_bands import band
        self.tables = tables
        self.path = Path(tempfile.mkdtemp(prefix='isolated-')) / 'run.db'
        with sqlite3.connect(self.path) as conn:
            self.seeded = iso.seed(pg, conn, tables)
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
                        'gaps': [str(g) for g in gaps][:100]}
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
    private = Run(pg, tables)
    private.point_legacy_here()
    sources = extseries_sources(network) if label == 'extseries' else sectorbench_sources(network)
    states, details = run_sources(private, sources, previous, network)
    changes = private.changes()
    shrunk = [t for t in tables if private.seeded[t] and private.count(t) < SHRINK_LIMIT * private.seeded[t]]
    counts = {t: (len(rows), len(gone)) for t, (rows, gone) in changes.items()}
    result = {'sources': details, 'not_moved': NOT_MOVED.get(label, {}), 'stopped': network.stopped}
    token = uuid.uuid4().hex
    if shrunk:  # the private file lost most of a table: nothing is published and collection is held
        outcome = f'held back: {", ".join(shrunk)} shrank below half'
        changes = {}
    else:
        outcome = outcome_of(states, counts)
    requests = dict(network.requests)
    try:
        run_id, _ = iso.publish(pg, label, started, outcome, changes, states, token=token, requests=requests, result=result)
    except Exception as exc:  # noqa: BLE001 - whether the commit took effect is settled from the run record
        run_id, outcome = settle(trial._pg, label, token, started, outcome, exc, requests, result)
    print(json.dumps({'run': run_id, 'label': label, 'outcome': outcome, 'requests_by_host': requests,
                      'statuses': dict(network.statuses), 'model_calls': 0}, ensure_ascii=False))
    return outcome

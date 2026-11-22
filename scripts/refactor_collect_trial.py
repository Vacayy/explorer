"""Isolated collection trial (PM #3 6937405301, safeguards 6937483535) — one job per one-shot container.

Writes only a writable copy of the projection file (/trial/work.db) and a disposable clone schema. The job runs the
unchanged legacy code in this process with the legacy database path pointed at the copy; every source request is
counted per host (name lookups, so every client counts, and responses of requests, curl_cffi and urllib) and a
429/403, or a source host reaching TRIAL_MAX_REQUESTS (default 20), aborts the job: further requests are refused
and the stop holds even if a source swallows the exception. Collect → check → apply is one function: a failed run, an aborted
source, a job record that is not 'ok', or a supplement table shrinking below half of what PG holds keeps PG
unchanged ('held back'). Nothing is sent (no Telegram/YouTube credentials are given) and collected text is never
printed. Results go to /trial/trial-log.jsonl.

  python scripts/refactor_collect_trial.py prepare
  python scripts/refactor_collect_trial.py run blog|prices|twrevenue|indexintraday
"""
import json
import os
import re
import runpy
import shutil
import socket
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

WORK = Path(os.environ.get('TRIAL_WORK', '/trial/work.db'))
LOG = WORK.parent / 'trial-log.jsonl'
NEW_DOCUMENT_CAP = 5
SHRINK_LIMIT = 0.5
BLOCKED = {403, 429}
# Upstream errors (5xx) from one host that stop the job (PM #3 6942746227, the history job); unset: no such stop.
MAX_ERRORS = int(os.environ.get('TRIAL_MAX_ERRORS', '0')) or None
MAX_REQUESTS = int(os.environ.get('TRIAL_MAX_REQUESTS', '20'))  # per source host, enforced before anything is applied (PM 6937645863)
# Per-host exceptions, 'host=cap,host=cap' (a job that needs more from one host, decided by the PM); others MAX_REQUESTS.
HOST_CAPS = {host: int(cap) for host, _, cap in (item.partition('=') for item in
             os.environ.get('TRIAL_HOST_CAPS', '').split(',') if item)}


def cap_of(host):
    """A host's cap: exact name, or a key starting with '.' for every host under that domain (a CDN's numbered hosts)."""
    if host in HOST_CAPS:
        return HOST_CAPS[host]
    return next((cap for key, cap in HOST_CAPS.items() if key.startswith('.') and host.endswith(key)), MAX_REQUESTS)
requests_by_host, statuses, per_host, errors = Counter(), Counter(), Counter(), Counter()
stopped = []  # the first stop reason; kept, because a source may swallow the exception raised at the stop


class Aborted(BaseException):
    """A source hit a stop rule; ordinary library retry handlers must not swallow it."""


class HeldBack(RuntimeError):
    """The run did not prove itself: PG stays unchanged."""


def _pg():
    import psycopg
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    live = os.environ.get('TRIAL_LIVE_SCHEMA')
    production = os.environ.get('COLLECT_TARGET') == 'live'
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema) or (schema != live if production else schema == live):
        raise ValueError('A disposable clone schema (not the live one) is required')
    return psycopg.connect(dsn, options=f'-c search_path={schema}', autocommit=True)


def _instrument():
    """Count source requests per host and stop at a block. The candidate database host is not a source."""
    resolve = socket.getaddrinfo

    def stop(reason):
        if not stopped:
            stopped.append(reason)
        raise Aborted(stopped[0])

    def getaddrinfo(host, *args, **kwargs):
        if host not in ('pg', 'localhost', '127.0.0.1') and isinstance(host, str):
            if stopped:
                stop(stopped[0])  # nothing more goes out after a stop
            if requests_by_host[host] >= cap_of(host):  # every client (urllib included) resolves before it connects
                stop(f'{host} reached the request cap {cap_of(host)}')
            requests_by_host[host] += 1
        return resolve(host, *args, **kwargs)
    socket.getaddrinfo = getaddrinfo

    def watch(status, url):
        host = re.sub(r'^https?://([^/:]+).*$', r'\1', str(url))
        statuses[f'{host} {status}'] += 1
        if status in BLOCKED:
            stop(f'{host} answered {status}')
        if MAX_ERRORS and status >= 500:
            errors[host] += 1
            if errors[host] >= MAX_ERRORS:
                stop(f'{host} answered {errors[host]} upstream errors')
        per_host[host] += 1
        if per_host[host] >= cap_of(host):
            stop(f'{host} reached the request cap {cap_of(host)}')  # no further request, nothing applied
    import urllib.error
    import urllib.request
    open_url = urllib.request.OpenerDirector.open

    def checked_urllib(self, request, *args, **kwargs):  # feedparser and the memo/blog connectors
        url = request if isinstance(request, str) else request.full_url
        try:
            response = open_url(self, request, *args, **kwargs)
        except urllib.error.HTTPError as exc:
            watch(exc.code, url)
            raise
        watch(response.status, url)
        return response
    urllib.request.OpenerDirector.open = checked_urllib
    try:
        import requests.adapters
        send = requests.adapters.HTTPAdapter.send

        def checked(self, request, *args, **kwargs):
            response = send(self, request, *args, **kwargs)
            watch(response.status_code, request.url)
            return response
        requests.adapters.HTTPAdapter.send = checked
    except ImportError:
        pass
    try:
        from curl_cffi import requests as curl
        request = curl.Session.request

        def checked_curl(self, method, url, *args, **kwargs):
            response = request(self, method, url, *args, **kwargs)
            watch(response.status_code, url)
            return response
        curl.Session.request = checked_curl
    except ImportError:
        pass


written = set()  # tables the job wrote in the collector file (sqlite authorizer)
housekeeping = []  # non-empty while database.init_db runs
other_files = set()  # other SQLite files the job wrote (recorded, never applied)
read = set()  # tables the job read from the collector file (_watch_reads)


def _watch_writes():
    """Record every table a statement inserts into, updates or deletes from, on every sqlite connection of the job."""
    connect = sqlite3.connect
    WRITES = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}

    def authorizer(action, table, *_rest):
        if action in WRITES and table and not table.startswith('sqlite_') and not housekeeping:
            written.add(table)
        return sqlite3.SQLITE_OK

    def elsewhere(target):
        def authorizer(action, table, _detail, database, _trigger):
            if action in WRITES and table and not table.startswith('sqlite_') and database != 'temp':
                other_files.add(target)  # a connection's TEMP copies (the computation path's) are not a file write
            return sqlite3.SQLITE_OK
        return authorizer

    def watched(*args, **kwargs):
        conn = connect(*args, **kwargs)
        # Only the collector file is the job's result; writes to other SQLite files (a library's own cache) are not
        # applied, only named in the run record (architect #3 6943390169).
        target = str(args[0] if args else kwargs.get('database', ''))
        conn.set_authorizer(authorizer if str(WORK) in target else elsewhere(target.split('?')[0]))
        return conn
    sqlite3.connect = watched
    # The legacy writer's own schema upkeep (database.init_db: idempotent backfill UPDATEs, usually no rows) is not
    # the job's collection; its statements would otherwise mark tables the job never collects.
    import database
    init_db = database.init_db

    def quiet_init_db(*args, **kwargs):
        housekeeping.append(True)
        try:
            return init_db(*args, **kwargs)
        finally:
            housekeeping.pop()
    database.init_db = quiet_init_db


def _watch_reads():
    """Record every table a statement reads from the collector file: what a job still needs from it."""
    connect = sqlite3.connect

    def watched(*args, **kwargs):
        conn = connect(*args, **kwargs)
        if str(WORK) in str(args[0] if args else kwargs.get('database', '')):
            def authorizer(action, table, *_rest):
                if action == sqlite3.SQLITE_READ and table and not table.startswith('sqlite_'):
                    read.add(table)
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorizer)
        return conn
    sqlite3.connect = watched


def _point_legacy_at_work():
    import config
    import database
    config.DB_PATH = database.DB_PATH = WORK


def _run_script(path, *argv):
    sys.argv = [path, *argv]
    try:
        runpy.run_path(path, run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise HeldBack(f'exit {exc.code}') from None


def _job_record(name, since, allowed=('ok',)):
    row = sqlite3.connect(WORK).execute('SELECT status FROM job_runs WHERE job=? AND ran_at>=? ORDER BY id DESC LIMIT 1',
                                        (name, since)).fetchone()
    if row is None or row[0] not in allowed:
        raise HeldBack(f'job record {name}: {row[0] if row else "missing"}')
    return row[0]


def _apply_supplement(pg, tables):
    """Safeguard 1: a table that shrank below half of what PG holds is not replaced."""
    from pipeline.postgres_collector_bridge import refresh_supplement
    work = sqlite3.connect(WORK)
    for table in tables:
        held = pg.execute('SELECT row_count FROM legacy_supplement_tables WHERE table_name=%s', (table,)).fetchone()[0]
        now = work.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        if held and now < SHRINK_LIMIT * held:
            raise HeldBack(f'{table} shrank {held} -> {now}')
    return refresh_supplement(pg, str(WORK), tables)


def job_table(name):
    """(script argv, job record name or None, supplement tables) of the table-collecting jobs."""
    return {'prices': (['scripts/ingest_prices.py', '--daily'], 'prices', ['stock_prices', 'job_runs']),
            'twrevenue': (['scripts/collect_tw_revenue.py'], None, ['tw_monthly_revenue']),
            'indexintraday': (['scripts/index_intraday.py'], 'index_intraday', ['index_intraday', 'job_runs'])}[name]


def run_blog(pg):
    """One RSS feed, at most NEW_DOCUMENT_CAP new documents (each tagged once); existing documents are not touched."""
    from pipeline.connectors.blog import BlogConnector
    return run_documents(pg, [BlogConnector([os.environ['TRIAL_FEED']])], NEW_DOCUMENT_CAP)


def run_documents(pg, connectors, cap, before_publish=None):
    """The connectors' new documents, at most `cap` per run (each stored and tagged as by ingest; the rest wait for
    the next run because they are not stored); existing documents are not touched. New documents are published."""
    from pipeline.runner import run_source
    from pipeline.store import store_document
    from pipeline.postgres_collected_documents_fixture import publish
    work = sqlite3.connect(WORK)
    work.row_factory = sqlite3.Row
    floors = _published_floors(work)
    known = {(r[0], r[1]) for r in work.execute('SELECT source_type, source_id FROM raw_documents')}
    counts = Counter()

    def capped(doc):
        if (doc.source_type, doc.source_id) in known:
            counts['existing_skipped'] += 1
            return {'status': 'unchanged'}
        if counts['new'] >= cap:
            counts['over_cap_skipped'] += 1
            return {'status': 'unchanged'}
        result = store_document(doc)
        counts[result['status']] += 1
        return result
    stats = {}
    for connector in connectors:
        name = type(connector).__name__
        try:
            stats[name] = run_source(connector, store=capped)
        except Aborted:
            raise
        except Exception as exc:  # noqa: BLE001 - one source failing does not stop the others (ingest.py)
            stats[name] = f'failed: {type(exc).__name__}: {str(exc)[:120]}'
    work.close()
    if stopped:
        raise Aborted(stopped[0])  # a source swallowed the stop: still nothing published
    if before_publish is not None:
        before_publish()
    work = sqlite3.connect(WORK)
    if work.execute('SELECT COALESCE(max(id),0) FROM raw_documents').fetchone()[0] <= floors['document_floor']:
        return {'stats': stats, 'counts': dict(counts), 'published': 0}
    work.row_factory = sqlite3.Row
    published = publish(pg, work, **floors)
    _published_floors(work, advance=True)
    work.commit()
    return {'stats': stats, 'counts': dict(counts), 'published': published}


FLOOR_TABLES = (('document_floor', 'raw_documents'), ('entity_floor', 'entities'), ('keyword_floor', 'entity_keywords'),
                ('relation_floor', 'entity_relations'))


def band_ids(work):
    """The candidate's id band on the work copy (pipeline.postgres_id_bands, every AUTOINCREMENT table); idempotent."""
    from pipeline.postgres_id_bands import band
    moved = band(work)
    work.commit()
    return moved


def _published_floors(work, advance=False):
    """Highest ids already published from this collector file. A run stopped before publishing leaves them, so its
    stored documents go out with the next published run (a fresh trial copy starts from its current maxima)."""
    work.execute('CREATE TABLE IF NOT EXISTS candidate_publish_floor (name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
    current = {name: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for name, table in FLOOR_TABLES}
    if advance:
        work.executemany('INSERT OR REPLACE INTO candidate_publish_floor VALUES (?,?)', current.items())
        return current
    kept = dict(work.execute('SELECT name, value FROM candidate_publish_floor').fetchall())
    if not kept:
        work.executemany('INSERT INTO candidate_publish_floor VALUES (?,?)', current.items())
        work.commit()
        return current
    return {name: kept.get(name, current[name]) for name in current}


def main():
    command = sys.argv[1]
    if command == 'prepare':
        source = Path('/projection') / json.loads(Path('/projection/current.json').read_text())['file']
        shutil.copyfile(source, WORK)
        os.chmod(WORK, 0o600)
        # A projection's full-text table is not kept in step with its documents; a collector file is (the MacBook's).
        with sqlite3.connect(WORK) as work:
            if work.execute("SELECT 1 FROM sqlite_master WHERE name='doc_fts'").fetchone():
                work.execute("INSERT INTO doc_fts(doc_fts) VALUES('rebuild')")
            band_ids(work)
        print('prepared work copy', WORK.stat().st_size)
        return
    job = sys.argv[2]
    pg = _pg()
    from pipeline import llm, postgres_llm_calls
    postgres_llm_calls.install(llm, _pg)  # model calls of this run, in the clone
    _instrument()
    _point_legacy_at_work()
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    entry = {'job': job, 'started': started}
    try:
        if job == 'blog':
            entry['result'] = run_blog(pg)
        else:
            argv, record, tables = job_table(job)
            os.chdir('/app')
            _run_script(*argv)
            if stopped:
                raise Aborted(stopped[0])
            if record:
                _job_record(record, started)
            entry['applied'] = _apply_supplement(pg, tables)
        entry['outcome'] = 'applied'
    except Aborted as exc:
        entry['outcome'] = f'aborted: {exc}'
    except HeldBack as exc:
        entry['outcome'] = f'held back: {exc}'
    except Exception as exc:  # noqa: BLE001 - any failure keeps PG unchanged
        entry['outcome'] = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    entry['requests_by_host'] = dict(requests_by_host)
    entry['statuses'] = dict(statuses)
    entry['model_calls'] = pg.execute("SELECT count(*) FROM llm_calls WHERE created_at>=%s", (started,)).fetchone()[0]
    with open(LOG, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    print(json.dumps(entry, ensure_ascii=False))


if __name__ == '__main__':
    main()

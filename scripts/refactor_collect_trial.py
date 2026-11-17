"""Isolated collection trial (PM #3 6937405301, safeguards 6937483535) — one job per one-shot container.

Writes only a writable copy of the projection file (/trial/work.db) and a disposable clone schema. The job runs the
unchanged legacy code in this process with the legacy database path pointed at the copy; every source request is
counted per host and a 429/403 aborts the job. Collect → check → apply is one function: a failed run, an aborted
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
requests_by_host, statuses = Counter(), Counter()


class Aborted(RuntimeError):
    """A source answered 403/429 (or a block page): stop, never retry, never apply."""


class HeldBack(RuntimeError):
    """The run did not prove itself: PG stays unchanged."""


def _pg():
    import psycopg
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    live = os.environ.get('TRIAL_LIVE_SCHEMA')
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema) or schema == live:
        raise ValueError('A disposable clone schema (not the live one) is required')
    return psycopg.connect(dsn, options=f'-c search_path={schema}', autocommit=True)


def _instrument():
    """Count source requests per host and stop at a block. The candidate database host is not a source."""
    resolve = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if host not in ('pg', 'localhost', '127.0.0.1') and isinstance(host, str):
            requests_by_host[host] += 1
        return resolve(host, *args, **kwargs)
    socket.getaddrinfo = getaddrinfo

    def watch(status, url):
        host = re.sub(r'^https?://([^/:]+).*$', r'\1', str(url))
        statuses[f'{host} {status}'] += 1
        if status in BLOCKED:
            raise Aborted(f'{host} answered {status}')
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


def _job_record(name, since):
    row = sqlite3.connect(WORK).execute('SELECT status FROM job_runs WHERE job=? AND ran_at>=? ORDER BY id DESC LIMIT 1',
                                        (name, since)).fetchone()
    if row is None or row[0] != 'ok':
        raise HeldBack(f'job record {name}: {row[0] if row else "missing"}')


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
    from pipeline.runner import run_source
    from pipeline.store import store_document
    from pipeline.postgres_collected_documents_fixture import publish
    work = sqlite3.connect(WORK)
    work.row_factory = sqlite3.Row
    feed = os.environ['TRIAL_FEED']
    floors = {name: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for name, table in (
        ('document_floor', 'raw_documents'), ('entity_floor', 'entities'), ('keyword_floor', 'entity_keywords'),
        ('relation_floor', 'entity_relations'))}
    known = {(r[0], r[1]) for r in work.execute('SELECT source_type, source_id FROM raw_documents')}
    counts = Counter()

    def capped(doc):
        if (doc.source_type, doc.source_id) in known:
            counts['existing_skipped'] += 1
            return {'status': 'unchanged'}
        if counts['new'] >= NEW_DOCUMENT_CAP:
            counts['over_cap_skipped'] += 1
            return {'status': 'unchanged'}
        result = store_document(doc)
        counts[result['status']] += 1
        return result
    stats = run_source(BlogConnector([feed]), store=capped)
    work.close()
    if not counts['new']:
        return {'stats': stats, 'counts': dict(counts), 'published': 0}
    work = sqlite3.connect(WORK)
    work.row_factory = sqlite3.Row
    published = publish(pg, work, **floors)
    return {'stats': stats, 'counts': dict(counts), 'published': published}


def main():
    command = sys.argv[1]
    if command == 'prepare':
        source = Path('/projection') / json.loads(Path('/projection/current.json').read_text())['file']
        shutil.copyfile(source, WORK)
        os.chmod(WORK, 0o600)
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

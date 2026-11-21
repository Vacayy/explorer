"""One scheduled collection job, run by the Mac mini scheduler in a one-shot container (single writer).

Same safeguards as the isolated trial (scripts/refactor_collect_trial.py): source requests counted per host, a
403/429 or a host reaching TRIAL_MAX_REQUESTS aborts with nothing applied, and collect → check → apply is one
function. Every run, whatever its outcome, is recorded in PG collect_runs. Before the cutover the target is the
disposable clone schema by default; the explicit live target must match the running API's schema.

Refused here: unconnected sends and the uncapped overnight tagging backfill.
Jobs not connected yet are recorded as 'unsupported' and not run.

  python scripts/refactor_collect_job.py <label>
  python scripts/refactor_collect_job.py --catchup <label,...>   # which of these to catch up now (prints JSON)
  python scripts/refactor_collect_job.py --stopped <label> <started UTC> <reason>   # record a run stopped at its limit
"""
import json
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refactor_collect_trial as trial  # noqa: E402 - the same harness and safeguards

SENDS = {'briefing', 'pfintraday', 'pfclose', 'observealerts', 'observeweekly'}
CONNECTED_SENDS = {'briefing', 'observeweekly', 'observealerts', 'pfintraday', 'pfclose'}
NEVER = {'backfill'}  # uncapped model calls; never scheduled automatically
# Table-collecting jobs: the unchanged script, then the supplement tables it actually wrote are replaced in PG
# (recorded by a sqlite authorizer; writing any table that is not a supplement table holds the run back).
TABLE_JOBS = {
              'usfund', 'krcompany', 'expfeed',
              'callmomentum', 'callfresh'}
# Jobs moved to the isolated path (scripts/refactor_isolated_jobs.py): a private file per run, publication by key.
# The tables they own are refused on this shared-file path, so the two paths never write the same table.
ISOLATED_JOBS = {'extseries', 'sectorbench', 'prices', 'pricefix', 'pricefactors', 'credit', 'retail', 'twrevenue', 'kalshi', 'indexintraday', 'trade',
                 'market', 'krmovers', 'usbriefing', 'markettoday'}
# Home jobs on the table path whose model calls are capped per run (each llm._execute is one call, its fallback
# included): a Market Today slot is one call; the US briefing is the macro light (macro.interpret), the macro issues
# (briefing.macro) and the synthesis (briefing.synthesize), one each (cached ones make none). Their network reads are optional (index values, macro series): the legacy job still
# writes its result when every one fails, so 'no source answered' does not hold them back.
TABLE_MODEL_CAPS = {'markettoday': 2, 'usbriefing': 6, 'trade': 6, 'usfund': 60,
                    # Brokers' forecasts from feed documents: one call per document, at most 25 documents per run.
                    'expfeed': 25,
                    # US earnings-call momentum (pending the PM's figures): digests of new calls (up to 22), extraction
                    # (60, fresh 20), summaries (30) and the season chain's core tickers.
                    'callmomentum': 120, 'callfresh': 60}
# The call collection's own proxy step (transcript.seed_proxies/extract_proxies) writes the candidate's native question
# tables; the daily questions job does the same extraction on PG (extract_numeric_native, the same 40), so it is skipped
# here rather than holding the whole run back.
NATIVE_STEPS_ELSEWHERE = {'callmomentum', 'callfresh'}
NETWORK_OPTIONAL = {'markettoday', 'usbriefing'}
# Legacy computations over saved data: the computation-button path (pipeline.postgres_scheduled_compute) — their
# overrides, graph diff and run records go to PG; model calls go through the usual gate and llm_calls.
# The chain's computation steps after document intake (scripts/run_chain.sh order), as their own labels.
CHAIN_STEPS = {'chain_macro_news': (['scripts/fetch_macro_news.py'], None),  # headlines: a collection step
               'chain_causal': (['scripts/extract_doc_causal.py', '--limit', '10'], 'extract_doc_causal'),
               'chain_signals': (['scripts/compute_signals.py'], None),
               'chain_narratives': (['scripts/compute_narratives.py', '--urgent'], 'compute_narratives'),
               'chain_events': (['scripts/extract_events.py', '--limit', '40'], 'extract_events'),
               'chain_actions': (['scripts/scan_actions.py'], None),  # fetches DART: a collection step (table path)
               # Image readings the intake missed (budget, failures) put into existing documents' bodies: at most 10 calls
               # per run (PM 6940286658); documents change, so it publishes revisions (table path).
               'chain_images': (['scripts/backfill_images.py', '--calls', '10', '--minutes', '8'], 'image_backfill'),
               'chain_digests': (['scripts/compute_digests.py'], None)}
CHAIN_TABLE_STEPS = {'chain_macro_news', 'chain_actions', 'chain_images'}
# Tables a collection job writes that are published as documents and graph rows (new ones, and revisions of existing
# ones against the published projection), not replaced as supplement tables; the full-text index is derived.
DOCUMENT_TABLES = {'raw_documents', 'enrichments', 'entity_links', 'entities', 'entity_keywords', 'entity_relations',
                   'narrative_edge_evidence'}
DERIVED = ('doc_fts',)
# The legacy file's own model call record: the PG llm_calls ledger (postgres_llm_calls) records every call already.
LOCAL_LEDGERS = {'llm_calls'}
# The sector map, sector and US industry screens and portfolio price history, refreshed from the collected prices
# (pipeline.postgres_sector_refresh; after the daily price collection and once after the cutover).
SECTOR_REFRESH = 'sectorrefresh'
# Discovery and analysis price history (scripts/refresh_market_history.py, D-177/D-220): its plan → collect → publish
# unchanged, from the collected prices; staged in the trial volume (a stopped run resumes), published in its own
# volume (architect #3 6942803616): only this job mounts it writable, the API reads it read-only
# (ANALYSIS_MARKET_HISTORY), and /projection stays read-only for every job.
MARKET_HISTORY = 'history'
HISTORY_DESTINATION = Path(os.environ.get('HISTORY_DESTINATION', '/history/market_history.sqlite'))
HISTORY_SHRINK_LIMIT = 0.5
# Peer monitor (scripts/refresh_peer_monitor.py): the collector unchanged on its own state volume (the MacBook's
# logs/peer-monitor at T0 continues the observation chain), read as the legacy API does, then recorded and shown through
# pipeline.postgres_peer_refresh (compare, one-transaction view switch, rollback). Only this job mounts the volume.
PEER = 'peer'
# Watch rule evaluation (scripts/evaluate_watch_rules.py, D-185; no model, no fetch): the group evaluate button's path
# (routers.postgres_owner_legacy_fixture) for every ledger with groups — the operator's, then each member's own, each
# on a connection scoped to that principal; the watch_evaluations diff goes to that principal's ledger.
WATCH = 'watch'
# The daily question refresh (scripts/refresh_questions.py): its native PG form,
# pipeline.postgres_question_refresh_fixture.refresh_all_native (numeric transcript observations, corpus sentiment,
# graph projection, re-judging every tracking question), with the API's search over the projection's chunk index.
# No network; its model calls are capped per run (QUESTIONS_MAX_CALLS). The Telegram alerts that follow the legacy
# job are sends (on at the cutover).
QUESTIONS = 'questions'
# Memory-heavy jobs take the shared heavy lock (pipeline.postgres_heavy_lock) for their whole run; busy for
# HEAVY_WAIT_SECONDS, the run is recorded as deferred and not started (architect #3 6948497320: never forced).
HEAVY = {'questions', 'proposals', 'callmomentum', 'callfresh', 'history'}
HEAVY_WAIT_SECONDS = int(os.environ.get('COLLECT_HEAVY_WAIT_SECONDS', '1800'))
QUESTIONS_MAX_CALLS = int(os.environ.get('COLLECT_QUESTIONS_MAX_CALLS', '80'))  # PM #3 6948235108: the legacy's result first
PEER_ROOT = Path(os.environ.get('PEER_ROOT', '/peer'))
COMPUTE_JOBS = {'narratives', 'contradictions', 'promote', 'proposals', 'bigpicture', 'sectoroverview',
                *(set(CHAIN_STEPS) - CHAIN_TABLE_STEPS)}
# chain: its document intake only (ingest with the registered sources, tagging included), capped per run and
# published; the chain's later steps (causal extraction, signals, narratives, digests…) are not connected yet.
FEED_SOURCES = os.environ.get('COLLECT_FEED_SOURCES', 'blog,note,memo,scrap')  # YouTube·Telegram excluded before cutover
MAX_NEW_DOCS = int(os.environ.get('COLLECT_MAX_NEW_DOCS', '20'))
MAX_MODEL_CALLS = int(os.environ.get('COLLECT_MAX_MODEL_CALLS', '20'))  # per computation run; reaching it holds back


def job_argv(label):
    """(script argv relative to the project, job record name) from the MacBook job list, unchanged."""
    if label in CHAIN_STEPS:
        return CHAIN_STEPS[label]
    from refactor_collect_scheduler import load_jobs
    jobs, rules = load_jobs()
    argv = next(argv for name, argv, _schedule in jobs if name == label)
    return [str(Path(argv[1]).relative_to(Path(argv[1]).parents[1])), *argv[2:]], rules.get(label, {}).get('record')


def _capture_documents():
    """The collector file's published documents and graph rows before the job (compared after it)."""
    import sqlite3
    from pipeline import postgres_collected_changes_fixture as changes
    work = sqlite3.connect(trial.WORK)
    work.row_factory = sqlite3.Row
    try:
        floors = trial._published_floors(work)
        return floors, changes.capture(work, floors['document_floor']), changes.capture_graph(work)
    finally:
        work.close()


def _publish_documents(pg, label, started, before):
    """New documents and revisions of existing ones (base: the projection the candidate publishes now), one transaction."""
    import sqlite3
    from pipeline import postgres_collected_changes_fixture as changes
    floors, documents, graph = before
    work = sqlite3.connect(trial.WORK)
    work.row_factory = sqlite3.Row
    origin = sqlite3.connect('file:/projection/current.db?mode=ro', uri=True)
    origin.row_factory = sqlite3.Row
    try:
        result = changes.publish_run(pg, work, origin, documents, run_id=f'scheduled {label} {started}', graph=graph,
                                     **floors)
        trial._published_floors(work, advance=True)
        work.commit()
        return {'added': len(result['added']), 'revised': len(result['revised']), 'kept': len(result['kept'])}
    finally:
        work.close()
        origin.close()


def job_runs_floor(work_path):
    """The highest job record id in the shared collector file before a run: the run's own records come after it."""
    import sqlite3
    with sqlite3.connect(f'file:{work_path}?mode=ro', uri=True) as work:
        return work.execute('SELECT COALESCE(max(id),0) FROM job_runs').fetchone()[0]


def new_job_runs(work_path, floor):
    """This run's job records (ids above `floor`), published by id. Records an earlier failed run left in the file
    stay below the floor and never go out with a later run; publishing the same records again changes nothing."""
    import sqlite3
    with sqlite3.connect(f'file:{work_path}?mode=ro', uri=True) as work:
        work.row_factory = sqlite3.Row
        return [dict(r) for r in work.execute('SELECT * FROM job_runs WHERE id > ? ORDER BY id', (floor,))]


def publish_job_runs(pg, runs):
    """Add this run's job records by id, in the caller's transaction. An id PG already holds with the same record is
    skipped (a repeated publication); with a different record it means the file and PG diverged: held back."""
    from pipeline.postgres_isolated_collect import _ordinals, _text, apply_keyed
    held = {_text((r['id'],)): r for r in runs}
    present = _ordinals(pg, 'job_runs', [(r['id'],) for r in runs], ('id',))
    if present:
        stored = dict(pg.execute('SELECT row_ordinal,row_data FROM legacy_supplement_rows WHERE table_name=%s AND '
                                 'row_ordinal=ANY(%s)', ('job_runs', list(present.values()))).fetchall())
        clash = [k[0] for k, ordinal in present.items() if stored.get(ordinal) != held[k]]
        if clash:
            raise trial.HeldBack(f'job record ids already in PG with other records: {clash[:5]}')
    fresh = [r for r in runs if _text((r['id'],)) not in present]
    return apply_keyed(pg, 'job_runs', ('id',), fresh)[0] if fresh else 0


def supplement_tables(pg, written):
    from pipeline.postgres_isolated_collect import KEYS
    if written & set(KEYS):
        raise trial.HeldBack(f'wrote tables owned by the isolated path: {sorted(written & set(KEYS))}')
    known = {name for (name,) in pg.execute('SELECT table_name FROM legacy_supplement_tables WHERE table_name=ANY(%s)',
                                            (sorted(written),))}
    if written - known:
        raise trial.HeldBack(f'wrote tables the candidate does not take from collection: {sorted(written - known)}')
    return sorted(written)


def require_us_briefing_synthesis(work, since):
    """An apparently successful warm-up with no synthesis must not be reported as a fresh briefing."""
    row = work.execute("SELECT summary FROM job_runs WHERE job='compute_briefing' AND ran_at>=? ORDER BY id DESC LIMIT 1",
                       (since,)).fetchone()
    summary = row[0] if row else ''
    if not summary or 'synthesis True' not in summary.split(' · '):
        raise trial.HeldBack('US briefing synthesis is missing')


def validate_partial_us_briefing(work, since):
    """Allow only the legacy partial caused by headline failures with usable movers."""
    import re
    row = work.execute("SELECT summary FROM job_runs WHERE job='compute_briefing' AND ran_at>=? ORDER BY id DESC LIMIT 1",
                       (since,)).fetchone()
    summary = row[0] if row else ''
    match = re.fullmatch(r'status partial · movers (\d+) · synthesis (True|False) · headline_failed (\d+)', summary or '')
    if not match or int(match[1]) < 1 or int(match[3]) < 1:
        raise trial.HeldBack('US briefing partial lacks verified movers or headline failure')
    return {'movers': int(match[1]), 'synthesis': match[2] == 'True', 'headline_failed': int(match[3])}



# Rows omitted by the legacy retention cleanup remain part of the live dataset.
BRIEFING_PRESERVE_KEYS = {
    'market_indicators': ('snapshot_date', 'indicator'), 'macro_signals': ('as_of',),
    'macro_news': ('url',), 'us_macro_issues': ('trade_date',),
    'us_ticker_news': ('ticker', 'url'), 'us_movers': ('trade_date', 'rank'),
}

USFUND_KEYS = {
    'us_quarterly': ('ticker', 'q', 'metric'),
    'us_segments': ('ticker', 'q', 'segment_name'),
    'us_customer_concentration': ('ticker', 'period_end', 'period_kind', 'customer', 'benchmark'),
    'consensus_snapshots': ('ticker', 'snap_date', 'period'),
}

def validate_usfund_keys(pg, work_path, tables):
    """Do not publish a whole replacement if a live natural key would disappear."""
    import sqlite3
    with sqlite3.connect(work_path) as work:
        for table in sorted(set(tables) & USFUND_KEYS.keys()):
            keys = USFUND_KEYS[table]
            info = work.execute(f'PRAGMA table_info("{table}")').fetchall()
            primary = tuple(row[1] for row in sorted((r for r in info if r[5]), key=lambda r: r[5]))
            if primary != keys:
                raise trial.HeldBack('US fundamentals key schema mismatch')
            existing = set(work.execute('SELECT ' + ','.join(f'"{key}"' for key in keys) + f' FROM "{table}"'))
            for (data,) in pg.execute('SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s', (table,)):
                row = data if isinstance(data, dict) else json.loads(data)
                key = tuple(row.get(k) for k in keys)
                if any(value is None for value in key) or key not in existing:
                    raise trial.HeldBack(f'US fundamentals existing keys missing in {table}')

def preserve_briefing_rows(pg, work_path, tables):
    """Restore PG-only keys to the work copy before its whole-table publication."""
    import sqlite3
    counts = {}
    with sqlite3.connect(work_path) as work:
        for table in sorted(set(tables) & BRIEFING_PRESERVE_KEYS.keys()):
            info = work.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = [row[1] for row in info]
            keys = BRIEFING_PRESERVE_KEYS[table]
            primary = tuple(row[1] for row in sorted((r for r in info if r[5]), key=lambda r: r[5]))
            expected = pg.execute('SELECT columns FROM legacy_supplement_tables WHERE table_name=%s', (table,)).fetchone()
            if not expected or primary != keys or list(expected[0]) != columns:
                raise trial.HeldBack('briefing preservation schema mismatch')
            query = f'INSERT OR IGNORE INTO "{table}" VALUES (' + ','.join('?' for _ in columns) + ')'
            where = ' AND '.join(f'"{key}"=?' for key in keys)
            seen = set()
            before = work.total_changes
            for (data,) in pg.execute('SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s', (table,)):
                row = data if isinstance(data, dict) else json.loads(data)
                key = tuple(row.get(k) for k in keys)
                if any(v is None for v in key) or key in seen or set(row) != set(columns):
                    raise trial.HeldBack('briefing preservation key conflict')
                seen.add(key)
                work.execute(query, [row[c] for c in columns])
                if work.execute(f'SELECT 1 FROM "{table}" WHERE {where}', key).fetchone() is None:
                    raise trial.HeldBack('briefing preservation insert failed')
            counts[table] = work.total_changes - before
    return counts


class ClosedIndexMarket(Exception):
    """An expected no-op outside index trading hours."""


def validate_trade_skip(status, written):
    """Accept the freshness no-op only when no business table was changed."""
    if status != 'skipped':
        return False
    if set(written) - LOCAL_LEDGERS - {'job_runs'}:
        raise trial.HeldBack('trade skipped after business table writes')
    return True


def closed_index_noop(label):
    """The legacy index collector intentionally does nothing outside market hours."""
    if label != 'indexintraday' or trial.requests_by_host or trial.other_files:
        return False
    from pipeline.index_intraday import due_markets
    return not due_markets()


def run_sector_refresh():
    import psycopg
    from pipeline import postgres_sector_refresh as sector
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    candidate = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # noqa: E731
    with candidate() as conn:
        base = sector.base_schema(conn)
    projection = '/projection/' + json.load(open('/projection/current.json'))['file']
    with psycopg.connect(dsn, autocommit=True) as admin:
        result = sector.refresh(admin, candidate, lambda store: psycopg.connect(dsn, options=f'-c search_path={store}'),
                                projection, base=base)
    return {'prices': result['after']['sector_market_prices'], 'load_seconds': result['load_seconds']}


def _guarded_history_publish(folder, destination, *, publish):
    """The script's publish into a staging folder beside the destination (same filesystem), then the architect's
    conditions (#3 6942709181) before the atomic rename: integrity_check ok, at least half the published rows, the
    as-of date not moving back. Any failure leaves the previous file in place."""
    import shutil
    import sqlite3
    staging = destination.parent / '.market-history-staged'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        if trial.stopped:  # a cap, a block or upstream errors: never publish a cut-short collection
            raise ValueError(f'Stopped: {trial.stopped[0]}')
        staged = staging / destination.name
        publish(folder, staged)
        with sqlite3.connect(f'file:{staged}?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Staged history failed integrity_check')
            rows, as_of = db.execute("SELECT (SELECT count(*) FROM prices), "
                                     "(SELECT value FROM metadata WHERE key='as_of')").fetchone()
        if destination.exists():
            with sqlite3.connect(f'file:{destination}?mode=ro', uri=True) as db:
                old_rows, old_as_of = db.execute("SELECT (SELECT count(*) FROM prices), "
                                                 "(SELECT value FROM metadata WHERE key='as_of')").fetchone()
            if rows < HISTORY_SHRINK_LIMIT * old_rows or json.loads(as_of) < json.loads(old_as_of):
                raise ValueError(f'Staged history {rows} rows to {json.loads(as_of)} against {old_rows} to '
                                 f'{json.loads(old_as_of)}: kept the published file')
        os.replace(staged, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def run_market_history():
    import functools
    import sqlite3
    import refresh_market_history as refresh
    refresh.SOURCE, refresh.DESTINATION = trial.WORK, HISTORY_DESTINATION
    refresh.ROOT = trial.WORK.parent / 'market-history'
    refresh.history.publish = functools.partial(_guarded_history_publish, publish=refresh.history.publish)
    before = refresh._published()
    code = refresh.main()
    summary = sqlite3.connect(trial.WORK).execute("SELECT status, summary FROM job_runs WHERE job='market_history' "
                                                  'ORDER BY id DESC LIMIT 1').fetchone()
    if code != 0:
        raise trial.HeldBack(summary[1] if summary else f'exit {code}')
    return {'before': before, 'after': refresh._published(), 'status': summary[0], 'summary': summary[1]}


def run_peer():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import psycopg
    import refresh_peer_monitor as peer
    from pipeline import postgres_peer_refresh
    from routers.peers import DATA, read_runtime
    catalog = json.loads((DATA / 'peer-catalog.json').read_text())
    seed = json.loads((DATA / 'peer-prices.json').read_text())
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    attempt = peer.refresh(PEER_ROOT, catalog, seed, now)  # a failed fetch publishes nothing and raises
    if trial.stopped:
        raise trial.HeldBack(f'Stopped: {trial.stopped[0]}')
    runtime = read_runtime(PEER_ROOT, DATA, now)
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    with psycopg.connect(dsn, options=f'-c search_path={schema}') as conn:
        shown = postgres_peer_refresh.apply(conn, runtime)
    return {'status': attempt['status'], 'as_of': attempt.get('asOf'), 'shown': shown,
            'companies': len(runtime.catalog.companies)}


def _cap_table_model_calls(limit):
    """Count actual engine attempts, including fallback; refuse before starting an extra process."""
    from pipeline import llm
    class Refusals(list):
        def restore(self):
            for name, original in originals.items():
                setattr(llm, name, original)

    made, refused, originals, lock = [0], Refusals(), {}, threading.Lock()

    def wrap(execute):
        def capped(*args, **kwargs):
            with lock:
                if made[0] >= limit:
                    refused.append(1)
                    raise trial.Aborted(f'model attempt cap {limit} reached')
                made[0] += 1
            return execute(*args, **kwargs)
        return capped

    for name in ('_run_claude_code', '_run_codex', '_run_api'):
        originals[name] = getattr(llm, name)
        setattr(llm, name, wrap(originals[name]))
    return refused


def _defer_big_picture_event():
    """market_today.py runs the weekly big picture's event check after the 16:00 wrap in the same process; its outputs
    (source digests, graph rows) are not supplement tables, so here it is only noted and runs afterwards as its own
    computation (the legacy also never lets its failure change the slot's result)."""
    from pipeline import weekly_big_picture
    requested, original = [], weekly_big_picture.run

    def note(trigger):
        requested.append(trigger)
        weekly_big_picture.run = original  # the deferred run below is the real one
        return {'status': 'deferred', 'trigger': trigger}
    weekly_big_picture.run = note
    return requested


PRICING_MAX_CALLS = 2  # counts both the primary and fallback attempts


def _defer_pricing():
    """compute_briefing.py ends with the pricing ledger extraction (pricing_ledger.extract_pending, one model call per
    briefing day not yet extracted); its tables are computed outputs, not supplement tables, so it is noted here and
    runs afterwards on the computation path, as the extraction button does (its failure never changes the briefing)."""
    from pipeline import pricing_ledger
    requested, original = [], pricing_ledger.extract_pending

    def note(limit=None):
        requested.append(limit)
        pricing_ledger.extract_pending = original
        return []
    pricing_ledger.extract_pending = note
    return requested


def _run_pricing():
    import psycopg
    from pipeline import postgres_scheduled_compute
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    try:
        return postgres_scheduled_compute.run('scripts/refactor_pricing_extract.py', [str(PRICING_MAX_CALLS)],
                                              lambda: psycopg.connect(dsn, options=f'-c search_path={schema}'),
                                              record='pricing_ledger', source='scheduled usbriefing pricing',
                                              max_calls=PRICING_MAX_CALLS)
    except Exception as exc:  # noqa: BLE001 - recorded with the briefing's run, never changes it
        return f'{type(exc).__name__}: {str(exc)[:200]}'


def _run_big_picture_event():
    import psycopg
    from pipeline import postgres_scheduled_compute
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    try:
        return postgres_scheduled_compute.run('scripts/weekly_big_picture.py', ['--event'],
                                              lambda: psycopg.connect(dsn, options=f'-c search_path={schema}'),
                                              record='weekly_big_picture:event', source='scheduled markettoday event',
                                              max_calls=2)  # 16:00 event: at most two calls including fallback
    except Exception as exc:  # noqa: BLE001 - recorded with the slot's run, never changes it
        return f'{type(exc).__name__}: {str(exc)[:200]}'


def run_watch():
    import psycopg
    from pipeline import postgres_owner_legacy_fixture as owner_legacy
    from pipeline.postgres_legacy_projection import LegacyProjection, write_connection_var
    from pipeline.postgres_owner_overrides import record_outputs
    from pipeline.postgres_principals import owner_account, request_principal
    from pipeline.watch_rules import evaluate_all
    from routers.postgres_owner_legacy_fixture import LOCK, _Borrowed, _diff, _rows
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # noqa: E731
    projection = LegacyProjection(factory, '/projection', external=True)
    from fastapi import FastAPI
    from routers.postgres_legacy_read_fixture import install
    # As the button: the network guard and saved data (the legacy run's US price refresh is the collection jobs' part;
    # here it reports its failure in the summary), get_connection → the projection.
    install(FastAPI(), projection, database_host='pg')
    with factory() as pg:
        members = [row[0] for row in pg.execute(
            'SELECT DISTINCT a.principal FROM owner_legacy_rows r JOIN fixture_portfolio_accounts a ON a.id = r.account_id '
            'ORDER BY 1')] if owner_legacy._accounts(pg) else []
    results, mode = {}, os.environ.get('EXPLORER_ACCESS_MODE')
    for principal in [None, *members]:  # None: the operator (private mode reads the operator's ledger)
        if principal:
            os.environ['EXPLORER_ACCESS_MODE'] = 'public'
        token = request_principal.set(principal)
        try:
            conn, started = projection.write_connection(('job_runs',), scoped=True)  # its run record stays here
            try:
                before = _rows(conn)
                borrowed = write_connection_var.set(_Borrowed(conn))
                try:
                    summary = evaluate_all(None, False)
                finally:
                    write_connection_var.reset(borrowed)
                with factory() as pg:
                    pg.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK,))
                    changes = _diff(before, _rows(conn), owner_legacy.portfolio_group(pg))
                    stored = [pk for table, upserts, _ in changes if table == 'watch_evaluations' for pk in upserts]
                    if any(upserts or deletes for _, upserts, deletes in changes):
                        account = owner_account(pg, create=True)[0] if principal else None
                        sequences = dict(conn.execute('SELECT name,seq FROM temp.sqlite_sequence'))
                        owner_legacy.apply(pg, started, changes,
                                           {t: q for t, q in sequences.items() if t in owner_legacy.TABLES}, account=account)
                        record_outputs(pg, 'scheduled watch', [('watch_evaluations', pk) for pk in stored])
            finally:
                conn.close()
        finally:
            request_principal.reset(token)
            if mode is None:
                os.environ.pop('EXPLORER_ACCESS_MODE', None)
            else:
                os.environ['EXPLORER_ACCESS_MODE'] = mode
        results['operator' if principal is None else principal[:8]] = {'summary': summary, 'stored': len(stored)}
    return results


def run_questions():
    import psycopg
    from fastapi import FastAPI
    from pipeline import chat_tools, llm, postgres_legacy_embeddings
    from pipeline.postgres_legacy_projection import LegacyProjection, requester_is_operator
    from pipeline.postgres_question_refresh_fixture import refresh_all_native
    from pipeline.postgres_retrieval_jobs import legacy_retrieval
    from routers.postgres_legacy_read_fixture import install
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # noqa: E731
    projection = LegacyProjection(factory, '/projection', external=True)
    install(FastAPI(), projection, database_host='pg')
    postgres_legacy_embeddings.install(factory)
    legacy_retrieval('/projection/chunks.db', '/projection/' + json.load(open('/projection/current.json'))['file'])
    refused = _cap_table_model_calls(QUESTIONS_MAX_CALLS)

    def model(prompt, *, task):
        return llm.run(prompt, task=task, record_call=lambda *args: None)

    def search(query, *, k):
        return chat_tools.run_tool({'name': 'search_docs', 'args': {'query': query, 'k': k}})
    result = refresh_all_native(factory, run_llm=model, search=search)
    if refused:
        raise trial.HeldBack(f'model call cap {QUESTIONS_MAX_CALLS} reached (later calls refused; what ran is stored)')
    return result


def run_compute(label):
    import psycopg
    from pipeline import postgres_scheduled_compute
    argv, record = job_argv(label)
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    os.chdir('/app')
    return postgres_scheduled_compute.run(argv[0], argv[1:], lambda: psycopg.connect(dsn, options=f'-c search_path={schema}'),
                                          record=record, source=f'scheduled {label}', max_calls=MAX_MODEL_CALLS)


def run_feeds(pg, refused=None):
    from pipeline.registry import CONNECTORS
    if os.environ.get('COLLECT_FEED_MINIMAL_BLOG') == '1':
        youtube = CONNECTORS['youtube']() if os.environ.get('COLLECT_FEED_YOUTUBE') == '1' else None
        telegram = CONNECTORS['telegram']() if os.environ.get('COLLECT_FEED_TELEGRAM') == '1' else None
        return run_minimal_blog(pg, CONNECTORS['blog'](), refused, youtube=youtube, telegram=telegram)
    names = [name for name in FEED_SOURCES.split(',') if name]
    unknown = set(names) - set(CONNECTORS)
    if unknown:
        raise ValueError(f'Unknown sources: {sorted(unknown)}')
    def check_cap():
        if refused:
            raise trial.HeldBack(f'feed model call cap {MAX_MODEL_CALLS} reached')
    result = trial.run_documents(pg, [CONNECTORS[name]() for name in names], MAX_NEW_DOCS, before_publish=check_cap)
    result['sources'] = names
    result['steps_not_connected'] = ['extract_doc_causal', 'compute_signals', 'compute_narratives --urgent',
                                     'extract_events', 'backfill_images', 'scan_actions', 'compute_digests']
    return result


def _blog_document_known(key):
    return _feed_document_known('blog', key)


def _feed_document_known(source, key):
    with sqlite3.connect(f'file:{trial.WORK}?mode=ro', uri=True) as work:
        return work.execute('SELECT 1 FROM raw_documents WHERE source_type=? AND source_id=? LIMIT 1', (source, key)).fetchone() is not None


def _feed_blog_rss_differs(key, body):
    with sqlite3.connect(f'file:{trial.WORK}?mode=ro', uri=True) as work:
        row = work.execute("SELECT raw_content FROM raw_documents WHERE source_type='blog' AND source_id=?", (key,)).fetchone()
        return bool(row and (row[0] or '') != body)


def _mark_identical_feed_revisions(queue):
    with sqlite3.connect(f'file:{trial.WORK}?mode=ro', uri=True) as work:
        return queue.mark_identical_revisions(work)


def run_minimal_blog(pg, connector, refused=None, *, queue_path='/trial/feed-backlog.sqlite', youtube=None, telegram=None,
                     batch_marker=Path('/trial/feed-batch-trial'), image_marker=Path('/trial/feed-image-trial'),
                     batch_enabled=Path('/trial/feed-batch-enabled'),
                     telegram_trial=Path('/trial/feed-telegram-fallback-trial'),
                     telegram_enabled=Path('/trial/feed-telegram-fallback-enabled'),
                     revision_trial=Path('/trial/feed-blog-revision-trial'),
                     quarantine_path=Path('/trial/feed-quarantined-hosts.json')):
    """One blog reference, one queued document; a failure keeps this isolated feed on hold."""
    from pipeline.feed_backlog import FeedBacklog, fetch_pending_reference
    keyword_only = os.environ.get('COLLECT_FEED_KEYWORD_ONLY') == '1'
    strict_images = keyword_only or os.environ.get('COLLECT_FEED_STRICT_IMAGES') == '1'
    marker_exists = batch_marker.exists() or batch_marker.is_symlink()
    if marker_exists:
        info = batch_marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or batch_marker.read_text() != 'feed-batch-trial-v1\n':
            raise ValueError('Unrecognized feed batch trial marker')
    enabled_exists = batch_enabled.exists() or batch_enabled.is_symlink()
    if enabled_exists:
        info = batch_enabled.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or batch_enabled.read_text() != 'feed-batch-enabled-v1\n':
            raise ValueError('Unrecognized feed batch enable flag')
    telegram_trial_exists = telegram_trial.exists() or telegram_trial.is_symlink()
    if telegram_trial_exists:
        info = telegram_trial.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or telegram_trial.read_text() != 'feed-telegram-fallback-trial-v1\n':
            raise ValueError('Unrecognized Telegram fallback trial flag')
    telegram_enabled_exists = telegram_enabled.exists() or telegram_enabled.is_symlink()
    if telegram_enabled_exists:
        info = telegram_enabled.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or telegram_enabled.read_text() != 'feed-telegram-fallback-enabled-v1\n':
            raise ValueError('Unrecognized Telegram fallback enable flag')
    revision_trial_exists = revision_trial.exists() or revision_trial.is_symlink()
    if revision_trial_exists:
        info = revision_trial.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or revision_trial.read_text() != 'feed-blog-revision-trial-v1\n':
            raise ValueError('Unrecognized blog revision trial flag')
    batch_requested = os.environ.get('COLLECT_FEED_BATCH_MODEL') == '1' or marker_exists or enabled_exists
    if batch_requested and (keyword_only or not strict_images):
        raise ValueError('Feed batch model requires strict images and model mode')
    if batch_requested and not 1 <= MAX_MODEL_CALLS <= 2:
        raise ValueError('Feed batch trial requires an engine attempt cap of at most two')
    max_documents = 5 if batch_requested else min(MAX_NEW_DOCS, 5)
    if keyword_only:
        if MAX_MODEL_CALLS != 0:
            raise ValueError('Keyword-only feed requires a zero model attempt cap')
        from pipeline import enrich
        enrich.llm_available = lambda: False
    missing_images = []
    if strict_images:
        from pipeline import image_reading
        from pipeline.telegram_deferred import cached_images
        def blog_images(items, **kwargs):
            return cached_images(items, allow_missing=True, missing=missing_images, **kwargs)
        image_reading.read_images = blog_images  # existing notes only; preserve missing work in the queue
    from pipeline.feed_quarantine import load_hosts, blocked_ref, SourceQuarantined, guard_network
    hosts = load_hosts(quarantine_path)
    skip_ref = lambda name, ref: name == 'blog' and blocked_ref(ref, hosts)
    queue = FeedBacklog(queue_path)
    guard = guard_network(hosts)
    guard.__enter__()
    try:
        if queue.intent():
            raise trial.HeldBack('an earlier feed publication intent requires review')
        revision_result = {'revision_snapshot': 0, 'revision_requests': 0}
        if revision_trial_exists:
            from pipeline.feed_revision_trial import SnapshotUnavailable, stage_one
            try:
                revision_result = stage_one(queue, connector, _feed_document_known, revision_trial.unlink,
                                            needs_fetch=_feed_blog_rss_differs)
                if revision_trial.is_file():
                    revision_trial.unlink()  # no eligible reference
            except trial.Aborted:
                raise
            except SnapshotUnavailable as exc:
                revision_result = {'revision_snapshot': 0, 'revision_requests': exc.attempts,
                                   'revision_error': 'source_unavailable'}
            except SourceQuarantined:
                revision_result = {'revision_snapshot': 0, 'revision_requests': 0, 'revision_error': 'quarantined'}
            except Exception as exc:
                raise trial.HeldBack(f'revision snapshot failed: {type(exc).__name__}') from None
        image_trial = image_marker.exists() or image_marker.is_symlink()
        if image_trial:
            info = image_marker.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                    or image_marker.read_text() != 'feed-image-trial-v1\n' or keyword_only or not strict_images \
                    or not 1 <= MAX_MODEL_CALLS <= 2:
                raise ValueError('Invalid feed image trial marker or budget')
            from pipeline.feed_image_trial import stage_one
            try:
                image_result = stage_one(queue, image_marker.unlink)
                if image_marker.is_file():
                    image_marker.unlink()  # no eligible image; do not block later feed rounds
            except trial.Aborted:
                raise
            except Exception as exc:
                if image_marker.is_file():
                    image_marker.unlink()
                image_result = {'image_staged': 0, 'image_error': type(exc).__name__}
            return {'stats': {'feed': {'refs': 0}}, 'counts': {}, 'published': 0,
                    'sources': ['image-trial'], 'steps_not_connected': ['image result publication', 'calendar events'],
                    **image_result}
        deferred_analysis = False
        identical_revisions = _mark_identical_feed_revisions(queue)
        allowed = {'blog'} | ({'youtube'} if youtube is not None else set()) | ({'telegram'} if telegram is not None else set())
        unpublished_analysis = []
        for item in queue.analysis_pending():
            if not _feed_document_known(item[2].source_type, item[2].source_id):
                unpublished_analysis.append(item)
                if len(unpublished_analysis) >= max_documents:
                    break
        if queue.next(allowed=allowed) is None and not unpublished_analysis:
            if youtube is not None or telegram is not None or queue.next_pending_ref(allowed=allowed, skip=skip_ref) is None:
                from pipeline.base import SourceRef
                choices = [SourceRef(name) for name in sorted(allowed)]
                selected = queue.next_ref('feed-sources', choices)
                name = selected.key
                source_connector = {'blog': connector, 'youtube': youtube, 'telegram': telegram}[name]
                refs = source_connector.discover_channels() if name == 'youtube' else source_connector.discover()
                if name == 'blog' and hosts:
                    refs = [ref for ref in refs if not blocked_ref(ref, hosts)]
                ref = queue.next_ref(name, refs)
                if ref is None:
                    queue.advance_ref('feed-sources', selected)
                else:
                    if name == 'blog':
                        try:
                            posts = connector.discover_posts(ref)
                        except SourceQuarantined:
                            posts = []  # retain the source; do not contact the quarantined host
                    elif name == 'youtube':
                        posts = youtube.discover_channel(ref)
                    else:
                        from pipeline.telegram_deferred import page_reference
                        from services.telegram_service import scrape_channel
                        messages = scrape_channel(ref.key)
                        posts = [page_reference(ref.key, messages)] if messages else []
                    for post in posts:
                        if name == 'blog':
                            import hashlib
                            known = _blog_document_known(post.key)
                            payload = json.dumps(post.meta, sort_keys=True, ensure_ascii=False, default=str)
                            staged = SourceRef(key=hashlib.sha256(payload.encode()).hexdigest(), meta=post.meta)
                            queue.enqueue_ref(name, ref.key, staged, revision_pending=known)
                        else:
                            queue.enqueue_ref(name, ref.key, post)
                    queue.advance_ref(name, ref)
                    queue.advance_ref('feed-sources', selected)
            class OnePost:
                def fetch(self, ref):
                    return [connector.fetch_post(ref)]
            sources = {'blog': OnePost()}
            if youtube is not None:
                sources['youtube'] = youtube
            if telegram is not None:
                from pipeline.connectors.telegram import TelegramConnector
                from pipeline.telegram_deferred import ExistingMarks, cached_images, no_new_group_decision
                if telegram_trial_exists or telegram_enabled_exists:
                    from pipeline.telegram_marks_sync import GroupMarks
                    sources['telegram'] = TelegramConnector(mark_store=GroupMarks(trial._pg), judge=lambda *_: None,
                        image_reader=lambda items, **kwargs: cached_images(items, allow_missing=True, **kwargs))
                else:
                    sources['telegram'] = TelegramConnector(mark_store=ExistingMarks(), judge=no_new_group_decision,
                                                            image_reader=cached_images)
            from pipeline.telegram_deferred import NeedsAnalysis
            try:
                pending = queue.next_pending_ref(allowed=set(sources), skip=skip_ref)
                fallback_page = bool((telegram_trial_exists or telegram_enabled_exists) and pending and pending[1] == 'telegram')
                if fallback_page and telegram_trial_exists:
                    telegram_trial.unlink()  # consume before any group decision or page processing
                fetch_pending_reference(queue, sources, retain_names={'telegram'} if fallback_page else (), skip=skip_ref)
            except NeedsAnalysis:
                deferred_analysis = True  # snapshot remains queued; another source lane may run next time
            except SourceQuarantined:
                pass  # failed reference remains queued without contacting the quarantined host
        selected = unpublished_analysis[:max_documents]
        deferred_revisions = 0
        for item in queue.batch(allowed=allowed, limit=25):
            if _feed_document_known(item[2].source_type, item[2].source_id):
                queue.defer_revision(item[0])
                deferred_revisions += 1
            elif len(selected) < max_documents:
                selected.append(item)
        if strict_images:
            from pipeline.normalize import to_markdown
            from pipeline.telegram_deferred import NeedsAnalysis
            ready = []
            retain_analysis = set()
            for item in selected:
                try:
                    before_missing = len(missing_images)
                    item[2].markdown = to_markdown(item[2])
                    if len(missing_images) != before_missing:
                        retain_analysis.add(item[0])
                    ready.append(item)
                except NeedsAnalysis:
                    queue.defer_revision(item[0], reason='analysis')
                    deferred_analysis = True
            selected = ready
        if not selected:
            return {'stats': {'feed': {'refs': 1}}, 'counts': {}, 'published': 0,
                    'sources': sorted(allowed),
                    **revision_result,
                    'deferred_analysis': int(deferred_analysis),
                    'deferred_revisions': deferred_revisions,
                    'identical_revisions': identical_revisions,
                    'steps_not_connected': ['other feed sources', 'existing document revisions', 'chain postprocessing']}

        class QueuedDocuments:
            def discover(self):
                return [None]

            def fetch(self, _ref):
                return [item[2] for item in selected]

        batch = None
        consumed = [0]
        old_enrich = None
        if batch_requested and len(selected) > 1:
            if marker_exists:
                batch_marker.unlink()  # one scheduled trial only, even on a later model failure
            from pipeline import enrich, feed_enrichment
            documents = [{'title': item[2].title, 'markdown': item[2].markdown} for item in selected]
            try:
                batch = feed_enrichment.enrich_documents(documents)
            except trial.Aborted:
                raise
            except feed_enrichment.InvalidBatchResult as exc:
                # the queue keeps the documents; the answer stays beside it so the failed document can be named
                failed = Path(queue_path).parent / 'feed-batch-failed.json'
                with os.fdopen(os.open(failed, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as out:
                    json.dump({'reason': exc.reason, 'label': exc.label,
                               'documents': [[seq, doc.source_type, doc.source_id] for seq, _, doc in selected],
                               'raw': exc.raw}, out, ensure_ascii=False)
                raise trial.HeldBack(f'feed batch model failed: {exc.reason}') from None
            except Exception as exc:
                raise trial.HeldBack(f'feed batch model failed: {type(exc).__name__}') from None
            old_enrich = enrich.enrich

            def use_batch(title, markdown, **kwargs):
                index = consumed[0]
                if index >= len(documents) or (title, markdown) != (documents[index]['title'], documents[index]['markdown']):
                    raise ValueError('Feed batch input order changed')
                consumed[0] += 1
                return batch[index]

            enrich.enrich = use_batch

        def check_cap():
            if refused:
                raise trial.HeldBack(f'feed model call cap {MAX_MODEL_CALLS} reached')
            if batch is not None and consumed[0] != len(selected):
                raise trial.HeldBack('feed batch did not apply every model result')

        try:
            result = trial.run_documents(pg, [QueuedDocuments()], max_documents, before_publish=check_cap)
        finally:
            if old_enrich is not None:
                enrich.enrich = old_enrich
        if result['counts'].get('existing_skipped') or any(isinstance(v, str) for v in result['stats'].values()):
            raise trial.HeldBack('a selected document failed or became existing; retain the batch')
        for seq, _, _ in selected:
            if strict_images and seq in retain_analysis:
                queue.retain_analysis(seq)  # keep original and staged results for later image completion
                deferred_analysis = True
            else:
                queue.acknowledge(seq)  # only after successful PG publish and local floor commit
        result['sources'] = sorted({item[1] for item in selected})
        result.update(revision_result)
        result['deferred_analysis'] = int(deferred_analysis)
        result['deferred_revisions'] = deferred_revisions
        result['identical_revisions'] = identical_revisions
        result['quarantined_hosts'] = len(hosts)
        result['steps_not_connected'] = ['other feed sources', 'existing document revisions', 'chain postprocessing']
        return result
    finally:
        guard.__exit__(None, None, None)
        queue.close()


def run(label):
    from pipeline import postgres_collect_runs
    if label in ISOLATED_JOBS:
        import refactor_isolated_jobs
        return refactor_isolated_jobs.run(label)
    pg = trial._pg()
    if label not in HEAVY:
        return _run(label, pg, 0)
    import psycopg
    from pipeline.postgres_heavy_lock import wait_lock
    held = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True)  # kept open: the lock lives with it
    try:
        waited = wait_lock(held, seconds=HEAVY_WAIT_SECONDS)
        if waited is None:
            started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
            outcome = 'deferred: heavy lock busy'
            print(json.dumps({'run': postgres_collect_runs.record(pg, label, started, outcome), 'label': label,
                              'outcome': outcome}))
            return None
        return _run(label, pg, waited)
    finally:
        held.close()  # releases the heavy lock


def run_observe_weekly():
    """Render the existing weekly report from candidate ledgers; send to the configured operator only."""
    from pipeline import observe, postgres_observe_ledgers as ledgers
    from pipeline.notify import send_telegram
    from pipeline.postgres_legacy_projection import LegacyProjection
    from routers.postgres_owner_legacy_fixture import _Borrowed
    if not requester_is_operator():
        raise trial.HeldBack('operator projection is unavailable')
    with trial._pg() as pg:
        if not ledgers.ready(pg):
            raise trial.HeldBack('observation ledgers are not ready')
    projection = LegacyProjection(trial._pg, '/projection', external=True)
    conn = ledgers.observe_connection(projection, trial._pg, 7)
    old_get, old_flush = observe.get_connection, observe.flush
    observe.get_connection = lambda: _Borrowed(conn)
    observe.flush = lambda: None  # this one-shot process has no API request buffer
    try:
        message = observe.weekly_message()
        if not message or not send_telegram(message):
            raise trial.HeldBack('weekly report could not be sent')
    finally:
        observe.get_connection, observe.flush = old_get, old_flush
        conn.close()


def run_briefing(now=None):
    """Send the existing morning briefing once per KST day, respecting pre- and post-cutover run history."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    import database
    from pipeline import notify, ops, postgres_collect_runs, us_briefing  # preload legacy DB bindings
    from pipeline.postgres_legacy_projection import LegacyProjection, requester_is_operator
    from routers import spine_home  # noqa: F401 - preload legacy DB binding
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    if not requester_is_operator():
        raise trial.HeldBack('operator projection is unavailable')
    if now.weekday() >= 5 or now.hour < notify.BRIEFING_HOUR:
        return False
    since = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with trial._pg() as pg:
        if any(status in ('ok', 'skipped') for status, _ in postgres_collect_runs.runs(pg, 'briefing', since)):
            return False
    projection = LegacyProjection(trial._pg, '/projection', external=True)
    conn = projection.connect()
    try:
        if notify._attempted_today(conn):  # the MacBook's imported history
            return False
    finally:
        conn.close()
    original = database.get_connection
    rebound = [m for m in list(sys.modules.values()) if getattr(m, 'get_connection', None) is original]
    try:
        for module in rebound:
            module.get_connection = projection.connect
        database.get_connection = projection.connect
        message = notify.compose_briefing()
        if not message:
            return False
        if not notify.send_telegram(message):
            raise trial.HeldBack('briefing could not be sent')
        return True
    finally:
        for module in rebound:
            module.get_connection = original
        database.get_connection = original


def run_observe_alerts():
    """Evaluate operator alerts against live observation ledgers and persist their legacy deduplication state."""
    from pipeline import observe, postgres_observe_ledgers as ledgers, postgres_owner_overrides as overrides
    from pipeline.notify import send_telegram
    from pipeline.postgres_legacy_projection import LegacyProjection, requester_is_operator
    from routers.postgres_owner_legacy_fixture import _Borrowed
    if not requester_is_operator():
        raise trial.HeldBack('operator projection is unavailable')
    projection = LegacyProjection(trial._pg, '/projection', external=True)

    class WritableProjection:
        def connect(self):
            return projection.write_connection()[0]

    with trial._pg() as pg, pg.transaction():
        if not ledgers.ready(pg):
            raise trial.HeldBack('observation ledgers are not ready')
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-row-overrides',0))")
        conn = ledgers.observe_connection(WritableProjection(), trial._pg, 7)
        conn.execute('PRAGMA query_only=OFF')  # main file remains read-only; the state table is TEMP
        before = {'alert_state': {row['key']: dict(row) for row in conn.execute('SELECT * FROM temp.alert_state')}}
        old_get = observe.get_connection
        observe.get_connection = lambda: _Borrowed(conn)
        try:
            result = observe.check_alerts(send=send_telegram)
            after = {'alert_state': {row['key']: dict(row) for row in conn.execute('SELECT * FROM temp.alert_state')}}
            overrides.apply(pg, before, after)
        finally:
            observe.get_connection = old_get
            conn.close()
    if (result['fired'] or result['resolved']) and not result['sent']:
        raise trial.HeldBack('observation alert could not be sent')
    return bool(result['sent'])


@contextmanager
def portfolio_dart_connection(conn):
    """Use the projection and a disposable cache in this single-threaded one-shot job."""
    from services import dart_service
    from routers.postgres_owner_legacy_fixture import _Borrowed
    original = dart_service.get_connection
    original_get_dart = dart_service._get_dart

    def get_dart_with_temporary_cache():
        # OpenDartReader initializes a relative docs_cache directory. The source
        # tree is mounted read-only; restore the process cwd even on failure.
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix='explorer-dart-') as cache_dir:
            try:
                os.chdir(cache_dir)
                return original_get_dart()
            finally:
                os.chdir(previous_cwd)

    dart_service.get_connection = lambda: _Borrowed(conn)
    dart_service._get_dart = get_dart_with_temporary_cache
    try:
        yield
    finally:
        dart_service.get_connection = original
        dart_service._get_dart = original_get_dart


def portfolio_failure_location(exc):
    """Record only an exception class and application source location, never the exception message."""
    frames = traceback.extract_tb(exc.__traceback__)
    frame = next((item for item in reversed(frames) if '/app/backend/' in item.filename), None)
    name = Path(frame.filename).name if frame else 'unknown'
    if not name.replace('_', '').replace('.', '').isalnum() or len(name) > 80:
        name = 'unknown'
    return f'{type(exc).__name__} {name}:{frame.lineno if frame else 0}'


def run_portfolio_intraday():
    """Run the legacy operator alerts on writable TEMP state, then persist the sent keys and fresh quotes."""
    from pipeline import portfolio_alerts, postgres_live_tables, postgres_owner_overrides as overrides
    from pipeline.notify import send_telegram
    from pipeline.postgres_legacy_projection import LegacyProjection, requester_is_operator
    if not requester_is_operator():
        raise trial.HeldBack('operator projection is unavailable')
    projection = LegacyProjection(trial._pg, '/projection', external=True)
    failure = None
    result = None
    with trial._pg() as pg, pg.transaction():
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-row-overrides',0))")
        conn, _version = projection.write_connection(extra=('portfolio_quotes',))
        try:
            tables = ('portfolio_alerts_sent', 'portfolio_principle_state')
            snapshot = lambda: {table: {row['key']: dict(row) for row in conn.execute(f'SELECT * FROM temp."{table}"')}
                                for table in tables}
            before = snapshot()
            quotes_before = {row['stock_code']: dict(row) for row in conn.execute('SELECT * FROM temp.portfolio_quotes')}
            try:
                with portfolio_dart_connection(conn):
                    result = portfolio_alerts.run('intraday', conn=conn, send=send_telegram)
            except (trial.Aborted, Exception) as exc:
                failure = exc
                conn.rollback()  # preserve only legacy steps that committed before the failure
            after = snapshot()
            quotes_after = {row['stock_code']: dict(row) for row in conn.execute('SELECT * FROM temp.portfolio_quotes')}
            overrides.apply(pg, before, after)
            changed = [row for key, row in quotes_after.items() if quotes_before.get(key) != row]
            if changed:
                postgres_live_tables.upsert_rows(pg, 'portfolio_quotes', 'stock_code', changed)
        finally:
            conn.close()
    if failure is not None:
        if isinstance(failure, trial.Aborted):
            raise failure
        raise trial.HeldBack('portfolio alert failed after state reconciliation: ' + portfolio_failure_location(failure))
    if result.get('errors'):
        raise trial.HeldBack('portfolio alert reported partial failure after state reconciliation')
    return bool(result.get('sent'))



CLOSE_MODEL_ATTEMPTS = 10  # primary and fallback attempts combined
CLOSE_OVERRIDE_TABLES = ('portfolio_alerts_sent', 'portfolio_principle_state', 'catalysts',
                         'portfolio_event_estimates', 'transcript_calendar', 'entity_digests')

def close_snapshots(conn, overrides):
    """Capture close-alert rows by their actual unique key, not event natural keys."""
    out = {}
    for table in CLOSE_OVERRIDE_TABLES:
        rows = {}
        for row in conn.execute(f'SELECT * FROM temp."{table}"'):
            value = dict(row)
            key = overrides._key(table, value)
            if key in rows:
                raise trial.HeldBack('portfolio close has duplicate row keys')
            rows[key] = value
        out[table] = rows
    return out

def run_portfolio_close(send=None):
    """Run the legacy close path against writable projection shadows and existing ledgers."""
    import database
    from pipeline import portfolio_alerts, portfolio_events, portfolio_flow, transcript, digests  # preload bindings
    from pipeline import postgres_owner_overrides as overrides, postgres_live_tables
    from pipeline.notify import send_telegram
    from pipeline.postgres_legacy_projection import LegacyProjection, requester_is_operator
    from routers.postgres_owner_legacy_fixture import _Borrowed
    if not requester_is_operator():
        raise trial.HeldBack('operator projection is unavailable')
    projection = LegacyProjection(trial._pg, '/projection', external=True)
    failure, result = None, None
    with trial._pg() as pg, pg.transaction():
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-row-overrides',0))")
        conn, _version = projection.write_connection(extra=('portfolio_quotes', *CLOSE_OVERRIDE_TABLES))
        original = database.get_connection
        rebound = [m for m in list(sys.modules.values()) if getattr(m, 'get_connection', None) is original]
        try:
            before = close_snapshots(conn, overrides)
            quotes_before = {row['stock_code']: dict(row) for row in conn.execute('SELECT * FROM temp.portfolio_quotes')}
            for module in rebound:
                module.get_connection = lambda: _Borrowed(conn)
            database.get_connection = lambda: _Borrowed(conn)
            try:
                with portfolio_dart_connection(conn):
                    result = portfolio_alerts.run('close', conn=conn, send=send or send_telegram)
            except (trial.Aborted, Exception) as exc:
                failure = exc
                conn.rollback()
            after = close_snapshots(conn, overrides)
            # Legacy replacement by natural key may delete several distinct event IDs. Keep those existing IDs.
            for key, row in before['catalysts'].items():
                after['catalysts'].setdefault(key, row)
            overrides.apply(pg, before, after)
            quotes_after = {row['stock_code']: dict(row) for row in conn.execute('SELECT * FROM temp.portfolio_quotes')}
            changed = [row for key, row in quotes_after.items() if quotes_before.get(key) != row]
            if changed:
                postgres_live_tables.upsert_rows(pg, 'portfolio_quotes', 'stock_code', changed)
        finally:
            for module in rebound:
                module.get_connection = original
            database.get_connection = original
            conn.close()
    if failure is not None:
        if isinstance(failure, trial.Aborted):
            raise failure
        raise trial.HeldBack('portfolio close failed after state reconciliation: ' + portfolio_failure_location(failure))
    return result


def _run(label, pg, waited):
    import sqlite3
    from pipeline import llm, postgres_collect_runs, postgres_llm_calls
    if trial.WORK.exists():  # a work copy prepared before the bands existed takes them on its next run
        with sqlite3.connect(trial.WORK) as work:
            trial.band_ids(work)
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    entry = {}
    if (label in SENDS and label not in CONNECTED_SENDS) or label in NEVER:
        outcome = f'refused: {"sends messages" if label in SENDS else "uncapped model calls"}'
    elif label == 'observeweekly':
        trial._instrument()
        try:
            run_observe_weekly()
            outcome = 'applied: weekly report sent'
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:
            outcome = f'failed: {type(exc).__name__}'
    elif label == 'briefing':
        trial._instrument()
        try:
            outcome = 'applied: briefing sent' if run_briefing() else 'skipped: already sent or no content'
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:
            outcome = f'failed: {type(exc).__name__}'
    elif label == 'pfclose':
        trial._instrument()
        postgres_llm_calls.install(llm, trial._pg)
        refused = _cap_table_model_calls(CLOSE_MODEL_ATTEMPTS)
        try:
            result = run_portfolio_close()
            if refused or result.get('errors'):
                outcome = 'partial: portfolio close reported errors'
            else:
                outcome = 'applied: portfolio close sent' if result.get('sent') else 'skipped: no close alerts'
        except trial.Aborted as exc:
            outcome = 'partial: portfolio close model cap reached' if refused else f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:
            outcome = f'failed: {type(exc).__name__}'
        finally:
            refused.restore()
    elif label == 'observealerts':
        trial._instrument()
        try:
            outcome = 'applied: observation alert sent' if run_observe_alerts() else 'skipped: no alert changes'
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:
            outcome = f'failed: {type(exc).__name__}'
    elif label == 'pfintraday':
        trial._instrument()
        try:
            outcome = 'applied: portfolio alerts sent' if run_portfolio_intraday() else 'skipped: no new portfolio alerts'
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:
            outcome = f'failed: {type(exc).__name__}'
    elif label == SECTOR_REFRESH:
        try:
            entry['refreshed'] = run_sector_refresh()
            outcome = f"applied: prices to {entry['refreshed']['prices'][1]}, {entry['refreshed']['load_seconds']}s"
        except ValueError as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001 - the views keep reading the previous store
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label == MARKET_HISTORY:
        trial._instrument()
        trial._point_legacy_at_work()
        try:
            entry['history'] = run_market_history()
            outcome = f"{'skipped' if entry['history']['status'] == 'skipped' else 'applied'}: {entry['history']['summary']}"
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:  # under 90% of the published codes, or nothing collected: the file stays
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label == QUESTIONS:
        from pipeline import postgres_llm_calls
        postgres_llm_calls.install(llm, trial._pg)
        try:
            entry['questions'] = run_questions()
            r = entry['questions']
            outcome = (f"applied: rerolled {r['rerolled']}, numeric {r['numeric']}, sentiment {r['sentiment']}, "
                       f"projected {r['projected']}, stale {len(r['stale'])}, failed {len(r['failed'])}")
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label == WATCH:
        try:
            entry['watch'] = run_watch()
            stored = sum(item['stored'] for item in entry['watch'].values())
            outcome = f"applied: {stored} evaluations, {len(entry['watch'])} ledgers" if stored else 'skipped: nothing new'
        except Exception as exc:  # noqa: BLE001 - nothing stored for a ledger whose diff failed
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label == PEER:
        trial._instrument()
        trial._point_legacy_at_work()  # the collector's response cache and run record go to the work copy
        try:
            entry['peer'] = run_peer()
            outcome = (f"applied: {entry['peer']['as_of']}, {entry['peer']['companies']} companies" if entry['peer']['shown']
                       else f"skipped: {entry['peer']['as_of']} already shown")
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except (trial.HeldBack, ValueError) as exc:  # a stop, or the comparison: the shown runtime stays
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001 - a fetch failure: the collector records its attempt, nothing shown
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label in COMPUTE_JOBS:
        from pipeline.postgres_scheduled_compute import HeldBack, Skipped
        postgres_llm_calls.install(llm, trial._pg)
        try:
            entry['stored'] = run_compute(label)
            outcome = f"applied: {entry['stored']}"
        except Skipped as exc:
            outcome = f'skipped: {exc}'
        except HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001 - any failure: nothing stored
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    elif label not in TABLE_JOBS and label not in CHAIN_TABLE_STEPS and label != 'chain':
        outcome = 'unsupported: not connected to the candidate yet'
    else:
        postgres_llm_calls.install(llm, trial._pg)
        trial._instrument()
        trial._point_legacy_at_work()
        try:
            if label == 'chain':
                refused = _cap_table_model_calls(MAX_MODEL_CALLS)
                entry.update(run_feeds(pg, refused))
                if trial.requests_by_host and not trial.statuses:  # a connector may log its network errors and go on
                    raise trial.HeldBack('no source answered')
                failed = [name for name, stats in entry['stats'].items() if isinstance(stats, str)]
                done = f"new documents {entry['counts'].get('new', 0)}, published {entry['published']}"
                if failed and len(failed) == len(entry['stats']):
                    raise trial.HeldBack(f'every source failed: {", ".join(failed)}')
                outcome = (f'partial: {done}; failed {", ".join(failed)}' if failed else f'applied: {done}')
            else:
                argv, record = job_argv(label)
                os.chdir('/app')
                before = _capture_documents()
                runs_floor = job_runs_floor(trial.WORK)
                refused = _cap_table_model_calls(TABLE_MODEL_CAPS[label]) if label in TABLE_MODEL_CAPS else None
                event = _defer_big_picture_event() if label == 'markettoday' else None
                if label in NATIVE_STEPS_ELSEWHERE:
                    from pipeline import transcript
                    transcript.seed_proxies = lambda: 0
                    transcript.extract_proxies = lambda limit=40: {'extracted': 0, 'deferred_to': 'questions'}
                pricing = _defer_pricing() if label == 'usbriefing' else None
                trial._watch_writes()
                try:
                    trial._run_script(*argv)
                except trial.HeldBack:
                    if not refused:
                        raise
                if trial.stopped:
                    raise trial.Aborted(trial.stopped[0])
                if refused:
                    raise trial.HeldBack(f'model call cap {TABLE_MODEL_CAPS[label]} reached (a later call was refused)')
                if refused is not None:
                    refused.restore()  # follow-up pricing/event has its own independent budget
                if trial.requests_by_host and not trial.statuses and label not in NETWORK_OPTIONAL:
                    raise trial.HeldBack('no source answered')  # a script may record 'ok' with every fetch failed
                record_status = None
                if record:
                    allowed = ('ok', 'partial') if label == 'usbriefing' else ('ok', 'skipped') if label == 'trade' else ('ok',)
                    record_status = trial._job_record(record, started, allowed=allowed)
                if label == 'trade' and validate_trade_skip(record_status, trial.written):
                    raise ClosedIndexMarket('trade upstream unchanged')
                if label == 'usbriefing':
                    with sqlite3.connect(trial.WORK) as work:
                        if record_status == 'partial':
                            entry['briefing_partial'] = validate_partial_us_briefing(work, started)
                        else:
                            require_us_briefing_synthesis(work, started)
                written = {t for t in trial.written if not t.startswith(DERIVED)} - LOCAL_LEDGERS
                entry['written'] = sorted(written)
                if not written:
                    if closed_index_noop(label):
                        raise ClosedIndexMarket('index markets closed')
                    raise trial.HeldBack('wrote nothing')
                if written & DOCUMENT_TABLES:
                    entry['documents'] = _publish_documents(pg, label, started, before)
                rest = written - DOCUMENT_TABLES
                if label == 'usbriefing':
                    entry['preserved_rows'] = preserve_briefing_rows(pg, trial.WORK, rest)
                if label == 'usfund':
                    validate_usfund_keys(pg, trial.WORK, rest)
                runs = new_job_runs(trial.WORK, runs_floor) if 'job_runs' in rest else []
                rest = rest - {'job_runs'}  # never replaced whole: only this run's own records go out (below)
                with pg.transaction():  # the data and this run's job records, together
                    entry['applied'] = trial._apply_supplement(pg, supplement_tables(pg, rest)) if rest else {}
                    if runs:
                        entry['applied']['job_runs'] = publish_job_runs(pg, runs)
                outcome = ('partial: US briefing headline failures; ' if record_status == 'partial' else 'applied: ') + \
                    ', '.join(f'{t} {n}' for t, n in (entry['applied'] or {}).items())
                if event:  # the 16:00 wrap's big picture check, on the computation path after the slot is in PG
                    entry['big_picture_event'] = _run_big_picture_event()
                if pricing:  # the briefing's pricing ledger extraction, on the computation path after it is in PG
                    entry['pricing'] = _run_pricing()
        except ClosedIndexMarket as exc:
            outcome = f'skipped: {exc}'
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001 - any failure keeps PG unchanged
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
    if trial.other_files:
        entry['other_sqlite_written'] = sorted(trial.other_files)
    if waited:  # waited for the heavy lock (the builder or another heavy job held it)
        entry['waited_for_heavy_seconds'] = waited
    calls = pg.execute('SELECT count(*) FROM llm_calls WHERE created_at>=%s', (started,)).fetchone()[0]
    run_id = postgres_collect_runs.record(pg, label, started, outcome, requests=dict(trial.requests_by_host),
                                         model_calls=calls, result=entry)
    print(json.dumps({'run': run_id, 'label': label, 'outcome': outcome, 'requests_by_host': dict(trial.requests_by_host),
                      'statuses': dict(trial.statuses), 'model_calls': calls}, ensure_ascii=False))


def catchup(labels, now=None):
    """The MacBook's catch-up rule (pipeline.catchup, D-249) over collect_runs: the latest due time of each enabled
    calendar job without an applied run since then is due again (attempt spacing, attempt cap and window as before)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from pipeline import postgres_collect_runs
    from pipeline.catchup import decide, last_due
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from refactor_collect_scheduler import load_jobs
    jobs, rules = load_jobs()
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    pg = trial._pg()
    due_labels = []
    for label, _argv, schedule in jobs:
        if label not in labels or label not in rules or isinstance(schedule, int):
            continue
        due = last_due(schedule, now)
        if due is None:
            continue
        since = due.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        runs = [(status, datetime.strptime(at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc))
                for status, at in postgres_collect_runs.runs(pg, label, since)]
        go, why = decide(due, runs, now, rules[label].get('window_h'))
        if go:
            due_labels.append(label)
        print(f'# {label}: {why}', file=sys.stderr)
    print(json.dumps(due_labels))
    return due_labels


def record_stop(label, started, reason, kind='failed'):
    """A run the scheduler stopped (time limit) or found cut off (a reboot): recorded, so catch-up counts the attempt."""
    from pipeline import postgres_collect_runs
    print(postgres_collect_runs.record(trial._pg(), label, started, f'{kind}: {reason}'))


def ready():
    """The scheduler starts jobs only once PG answers and every migration is applied (a reboot may start it first)."""
    from pipeline.postgres_schema_migrations import pending
    missing = pending(trial._pg())
    print('ready' if not missing else f'pending migrations {missing}')
    return not missing


if __name__ == '__main__':
    if sys.argv[1] == '--catchup':
        catchup(set(sys.argv[2].split(',')))
    elif sys.argv[1] == '--stopped':
        record_stop(*sys.argv[2:6])
    elif sys.argv[1] == '--ready':
        sys.exit(0 if ready() else 1)
    else:
        run(sys.argv[1])

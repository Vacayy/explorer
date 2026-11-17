"""One scheduled collection job, run by the Mac mini scheduler in a one-shot container (single writer).

Same safeguards as the isolated trial (scripts/refactor_collect_trial.py): source requests counted per host, a
403/429 or a host reaching TRIAL_MAX_REQUESTS aborts with nothing applied, and collect → check → apply is one
function. Every run, whatever its outcome, is recorded in PG collect_runs. Before the cutover the target is the
disposable clone schema only (the trial's guard refuses the live candidate schema).

Refused here, whatever the scheduler asks: jobs that send (Telegram) and the uncapped overnight tagging backfill.
Jobs not connected yet are recorded as 'unsupported' and not run.

  python scripts/refactor_collect_job.py <label>
  python scripts/refactor_collect_job.py --catchup <label,...>   # which of these to catch up now (prints JSON)
  python scripts/refactor_collect_job.py --stopped <label> <started UTC> <reason>   # record a run stopped at its limit
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refactor_collect_trial as trial  # noqa: E402 - the same harness and safeguards

SENDS = {'briefing', 'pfintraday', 'pfclose', 'observealerts', 'observeweekly'}  # Telegram; on only after the cutover
NEVER = {'backfill'}  # uncapped model calls; never scheduled automatically
# Table-collecting jobs: the unchanged script, then the supplement tables it actually wrote are replaced in PG
# (recorded by a sqlite authorizer; writing any table that is not a supplement table holds the run back).
TABLE_JOBS = {'prices', 'twrevenue', 'indexintraday', 'credit', 'retail', 'market', 'krmovers', 'extseries',
              'sectorbench', 'kalshi', 'trade', 'usfund', 'krcompany'}
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


def supplement_tables(pg, written):
    known = {name for (name,) in pg.execute('SELECT table_name FROM legacy_supplement_tables WHERE table_name=ANY(%s)',
                                            (sorted(written),))}
    if written - known:
        raise trial.HeldBack(f'wrote tables the candidate does not take from collection: {sorted(written - known)}')
    return sorted(written)


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


def run_compute(label):
    import psycopg
    from pipeline import postgres_scheduled_compute
    argv, record = job_argv(label)
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], trial._pg().execute('SELECT current_schema()').fetchone()[0]
    os.chdir('/app')
    return postgres_scheduled_compute.run(argv[0], argv[1:], lambda: psycopg.connect(dsn, options=f'-c search_path={schema}'),
                                          record=record, source=f'scheduled {label}', max_calls=MAX_MODEL_CALLS)


def run_feeds(pg):
    from pipeline.registry import CONNECTORS
    names = [name for name in FEED_SOURCES.split(',') if name]
    unknown = set(names) - set(CONNECTORS)
    if unknown:
        raise ValueError(f'Unknown sources: {sorted(unknown)}')
    result = trial.run_documents(pg, [CONNECTORS[name]() for name in names], MAX_NEW_DOCS)
    result['sources'] = names
    result['steps_not_connected'] = ['extract_doc_causal', 'compute_signals', 'compute_narratives --urgent',
                                     'extract_events', 'backfill_images', 'scan_actions', 'compute_digests']
    return result


def run(label):
    from pipeline import llm, postgres_collect_runs, postgres_llm_calls
    pg = trial._pg()
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    entry = {}
    if label in SENDS or label in NEVER:
        outcome = f'refused: {"sends messages" if label in SENDS else "uncapped model calls"}'
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
        except trial.HeldBack as exc:  # under 90% of the published codes, or nothing collected: the file stays
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001
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
                entry.update(run_feeds(pg))
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
                trial._watch_writes()
                trial._run_script(*argv)
                if trial.stopped:
                    raise trial.Aborted(trial.stopped[0])
                if trial.requests_by_host and not trial.statuses:  # a script may record 'ok' with every fetch failed
                    raise trial.HeldBack('no source answered')
                if record:
                    trial._job_record(record, started)
                written = {t for t in trial.written if not t.startswith(DERIVED)}
                entry['written'] = sorted(written)
                if not written:
                    raise trial.HeldBack('wrote nothing')
                if written & DOCUMENT_TABLES:
                    entry['documents'] = _publish_documents(pg, label, started, before)
                rest = written - DOCUMENT_TABLES
                entry['applied'] = trial._apply_supplement(pg, supplement_tables(pg, rest)) if rest else {}
                outcome = 'applied: ' + ', '.join(f'{t} {n}' for t, n in (entry['applied'] or {}).items())
        except trial.Aborted as exc:
            outcome = f'aborted: {exc}'
        except trial.HeldBack as exc:
            outcome = f'held back: {exc}'
        except Exception as exc:  # noqa: BLE001 - any failure keeps PG unchanged
            outcome = f'failed: {type(exc).__name__}: {str(exc)[:200]}'
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

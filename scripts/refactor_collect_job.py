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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refactor_collect_trial as trial  # noqa: E402 - the same harness and safeguards

SENDS = {'briefing', 'pfintraday', 'pfclose', 'observealerts', 'observeweekly'}
CONNECTED_SENDS = {'briefing', 'observeweekly', 'observealerts', 'pfintraday'}  # other sends remain refused
NEVER = {'backfill'}  # uncapped model calls; never scheduled automatically
# Table-collecting jobs: the unchanged script, then the supplement tables it actually wrote are replaced in PG
# (recorded by a sqlite authorizer; writing any table that is not a supplement table holds the run back).
TABLE_JOBS = {'prices', 'twrevenue', 'indexintraday', 'credit', 'retail', 'market', 'krmovers', 'extseries',
              'sectorbench', 'kalshi', 'trade', 'usfund', 'krcompany', 'markettoday', 'usbriefing', 'expfeed',
              'callmomentum', 'callfresh'}
# Home jobs on the table path whose model calls are capped per run (each llm._execute is one call, its fallback
# included): a Market Today slot is one call; the US briefing is the macro light (macro.interpret), the macro issues
# (briefing.macro) and the synthesis (briefing.synthesize), one each (cached ones make none). Their network reads are optional (index values, macro series): the legacy job still
# writes its result when every one fails, so 'no source answered' does not hold them back.
TABLE_MODEL_CAPS = {'markettoday': 1, 'usbriefing': 3,
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


def supplement_tables(pg, written):
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
    """At most `limit` model calls in this run; a further one is refused and noted (the run is then held back)."""
    from pipeline import llm
    execute, made, refused = llm._execute, [0], []

    def capped(*args, **kwargs):
        if made[0] >= limit:
            refused.append(1)
            raise RuntimeError(f'model call cap {limit} reached')
        made[0] += 1
        return execute(*args, **kwargs)
    llm._execute = capped
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


PRICING_MAX_CALLS = 3  # one call per pending briefing day; at most three days per run (the rest: the next run)


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
        return run_minimal_blog(pg, CONNECTORS['blog'](), refused)
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


def run_minimal_blog(pg, connector, refused=None, *, queue_path='/trial/feed-backlog.sqlite'):
    """One blog reference, one queued document; a failure keeps this isolated feed on hold."""
    from pipeline.feed_backlog import FeedBacklog, fetch_pending_reference
    queue = FeedBacklog(queue_path)
    try:
        if queue.intent():
            raise trial.HeldBack('an earlier feed publication intent requires review')
        if queue.next() is None:
            if queue.next_pending_ref() is None:
                ref = queue.next_ref('blog', connector.discover())
                if ref is None:
                    raise trial.HeldBack('no blog sources are configured')
                posts = connector.discover_posts(ref)
                for post in posts:
                    queue.enqueue_ref('blog', ref.key, post)
                queue.advance_ref('blog', ref)
            class OnePost:
                def fetch(self, ref):
                    return [connector.fetch_post(ref)]
            fetch_pending_reference(queue, {'blog': OnePost()})
        item = queue.next()
        if item is None:
            raise trial.HeldBack('blog reference returned no documents')
        seq, _, doc = item

        class OneDocument:
            def discover(self):
                return [None]

            def fetch(self, _ref):
                return [doc]

        def check_cap():
            if refused:
                raise trial.HeldBack(f'feed model call cap {MAX_MODEL_CALLS} reached')

        result = trial.run_documents(pg, [OneDocument()], 1, before_publish=check_cap)
        queue.acknowledge(seq)  # only after successful PG publish and local floor commit
        result['sources'] = ['blog']
        result['steps_not_connected'] = ['other feed sources', 'existing document revisions', 'chain postprocessing']
        return result
    finally:
        queue.close()


def run(label):
    from pipeline import postgres_collect_runs
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
        raise trial.HeldBack('portfolio alert failed after state reconciliation')
    if result.get('errors'):
        raise trial.HeldBack('portfolio alert reported partial failure after state reconciliation')
    return bool(result.get('sent'))


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
                if trial.requests_by_host and not trial.statuses and label not in NETWORK_OPTIONAL:
                    raise trial.HeldBack('no source answered')  # a script may record 'ok' with every fetch failed
                if record:
                    trial._job_record(record, started)
                if label == 'usbriefing':
                    with sqlite3.connect(trial.WORK) as work:
                        require_us_briefing_synthesis(work, started)
                written = {t for t in trial.written if not t.startswith(DERIVED)} - LOCAL_LEDGERS
                entry['written'] = sorted(written)
                if not written:
                    raise trial.HeldBack('wrote nothing')
                if written & DOCUMENT_TABLES:
                    entry['documents'] = _publish_documents(pg, label, started, before)
                rest = written - DOCUMENT_TABLES
                entry['applied'] = trial._apply_supplement(pg, supplement_tables(pg, rest)) if rest else {}
                outcome = 'applied: ' + ', '.join(f'{t} {n}' for t, n in (entry['applied'] or {}).items())
                if event:  # the 16:00 wrap's big picture check, on the computation path after the slot is in PG
                    entry['big_picture_event'] = _run_big_picture_event()
                if pricing:  # the briefing's pricing ledger extraction, on the computation path after it is in PG
                    entry['pricing'] = _run_pricing()
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

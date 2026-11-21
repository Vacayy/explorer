"""Mac mini collection schedule (single writer).

Reads the MacBook's launchd job list as it is (scripts/install_launchd.py JOBS and its CATCHUP rules) and runs
when each job would run, in Asia/Seoul time as launchd did on the MacBook.

--plan lists the run times; nothing is executed.
--run executes only the jobs named in --enable, one at a time (a run started while another runs waits in a
queue; repeats of a waiting job coalesce, as launchd does), each as a one-shot container
(scripts/refactor_collect_trial.sh job <label> → scripts/refactor_collect_job.py, per-host request cap, record
in PG collect_runs). A file lock keeps a second scheduler from starting. Unconnected sends and the overnight backfill
are refused. Missed runs are caught up as on the MacBook (pipeline.catchup over collect_runs, checked at start
and every 30 minutes while idle). The live target is opt-in; without it only a disposable clone is allowed.
Nothing is enabled by default.

  python scripts/refactor_collect_scheduler.py --plan 24                       # the next 24 hours
  python scripts/refactor_collect_scheduler.py --run --enable indexintraday    # loop
  python scripts/refactor_collect_scheduler.py --run --enable prices --once prices   # one run now, then exit
"""
import argparse
import fcntl
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))  # refactor_collect_engine, refactor_collect_job
LOCK = Path(os.environ.get('COLLECT_SCHEDULER_LOCK', Path.home() / 'server-data/review/refactor-single/collect-scheduler.lock'))
HOLD = Path(os.environ.get('COLLECT_SCHEDULER_HOLD', Path.home() / 'server-data/review/refactor-single/collect-scheduler.hold'))
FEED_HOLD = Path(os.environ.get('COLLECT_FEED_HOLD', Path.home() / 'server-data/review/refactor-single/collect-feed.hold'))
JOB_SECONDS = int(os.environ.get('COLLECT_JOB_SECONDS', '3600'))  # one job's time limit (the MacBook chain step limit)
TICK_SECONDS = 20
# Jobs on the isolated path (refactor_isolated_jobs.py): a failed source publishes nothing and holds only itself.
ISOLATED_JOBS = {'extseries', 'sectorbench', 'prices', 'credit', 'retail', 'twrevenue', 'kalshi', 'indexintraday', 'trade',
                 'market', 'krmovers', 'usbriefing', 'markettoday'}
FIRST = ('usbriefing',)
# A hold still on at 06:20 means the 06:30 US briefing will not run: the operator is told once that day (never acted on).
BRIEFING_ALERT = ((6, 20), (6, 30))
BRIEFING_ALERT_MARK = Path(os.environ.get('COLLECT_BRIEFING_ALERT_MARK', Path.home() / 'server-data/review/refactor-single/collect-scheduler.briefing-alert'))
# One heavy job at a time on the 7.7GiB VM: the scheduler runs one job at a time, and a heavy job also takes the PG
# heavy lock the projection builder takes (refactor_collect_job.HEAVY, pipeline.postgres_heavy_lock).
JOB_MEMORY = {'proposals': '3584m',  # measured peak 2.9GiB (weekly); every other job 2g
              'questions': '3584m',  # the search model and index: 2.2GiB measured, killed at 2g
              'callmomentum': '3584m', 'callfresh': '3584m'}
# The MacBook's 30-minute chain (scripts/run_chain.sh) in its order: one container per step, each recorded; a step
# that fails does not stop the next (as there). Not here: probe_llm (the gate does it), briefing catch-up (sends),
# vault export and the search index (the projection builder). Image backfill runs with at most 10 calls.
CHAIN_SEQUENCE = ('chain_macro_news', 'chain', 'chain_causal', 'chain_signals', 'chain_narratives', 'chain_events',
                  'chain_images', 'chain_actions', 'chain_digests')
# Per-run host caps of the intake (PM 6938365215, 6940286658): ~30 Naver blog feeds, 32 Telegram channel pages,
# 25 YouTube channel feeds plus captions, Telegram images read within the 30-minute image budget (numbered CDN hosts).
JOB_HOST_CAPS = {'chain': 'rss.blog.naver.com=40,t.me=40,www.youtube.com=40,.telesco.pe=40',
                 # A prior daily run used 21 Naver and 263 Yahoo requests; enforce a bounded production run.
                 'prices': 'polling.finance.naver.com=30,.finance.yahoo.com=300',
                 'pfintraday': 'polling.finance.naver.com=30',
                 # one chart request per listed code (3,017 now), retries counted in the same cap (PM 6942746227)
                 'history': 'fchart.stock.naver.com=3200',
                 # credit (macbook-source #3 6942831447): 34 companies — issuer scan and history on the scanner host,
                 # symbol search as the fallback, 10 Treasury series from FRED; any other host keeps the default 20
                 'credit': 'scanner.tradingview.com=150,symbol-search.tradingview.com=60,data.tradingview.com=150,fred.stlouisfed.org=12',
                 # Four categories, up to 18 trending events and pinned-event lookups/candles.
                 'kalshi': 'api.elections.kalshi.com=60',
                 # Company facts, income statements and customer concentration across followed US issuers.
                 'usfund': 'data.sec.gov=300,www.sec.gov=300',
                 # peer: one daily-price page per catalog company (104 now)
                 'peer': 'stock.naver.com=120',
                 # US briefing: macro series from FRED (three tries when all fail), Yahoo quotes·charts·headlines for the
                 # indices, macro proxies and the movers; newswire feeds keep the default 20
                 'usbriefing': 'fred.stlouisfed.org=40,.finance.yahoo.com=150',
                 # call momentum (pending the PM): SEC filings per followed ticker, Alpha Vantage within its 22 budget,
                 # Fool transcripts, the monthly Nasdaq-100 sync, the season chain's estimates
                 'callmomentum': 'data.sec.gov=300,www.sec.gov=300,www.alphavantage.co=30,www.fool.com=60,'
                                 'api.nasdaq.com=5,financialmodelingprep.com=60,.finance.yahoo.com=150',
                 'callfresh': 'www.fool.com=60,data.sec.gov=100,www.sec.gov=100'}
# A job's own stop rules: history stops at 50 upstream errors, credit at 10 (403/429 stop every job at the first).
JOB_ENV = {'history': {'TRIAL_MAX_ERRORS': '50'}, 'credit': {'TRIAL_MAX_ERRORS': '10'}, 'peer': {'TRIAL_MAX_ERRORS': '10'}}
# The intake's sources after the cutover (registry order: scrap reads Telegram documents); before it, the default
# (no Telegram or YouTube) keeps the MacBook the only collector from this IP.
CUTOVER_FEED_SOURCES = 'blog,telegram,note,youtube,memo,scrap'
CATCHUP_SECONDS = 1800  # the MacBook's catchup job ran every 30 minutes


# Jobs the Mac mini adds to the MacBook's list: the sector tables after the daily prices (KST, weekdays like prices).
EXTRA_JOBS = [('sectorrefresh', ['scripts/refactor_sector_refresh.py'], [{'Weekday': d, 'Hour': 21, 'Minute': 0} for d in range(1, 6)]),
              # The candidate PG backup daily (the MacBook's backup hour) and a restore check of the newest dump weekly:
              # a dump that does not restore is not a backup (architect #3 6947453973).
              ('pgbackup', ['scripts/refactor_pg_backup.sh', 'rotate'], {'Hour': 4, 'Minute': 30}),
              ('pgrestorecheck', ['scripts/refactor_pg_backup.sh', 'check-current'], {'Weekday': 0, 'Hour': 5, 'Minute': 0})]
# Jobs that need the host's docker CLI (the backup execs into the PG container), run here instead of in a job container;
# recorded in collect_runs like the others. The check requires the dump's full table inventory.
HOST_JOBS = {'pgbackup': ('scripts/refactor_pg_backup.sh', 'rotate'),
             'pgrestorecheck': ('scripts/refactor_pg_backup.sh', 'check-current')}
HOST_OK = {'pgbackup': '-candidate.dump', 'pgrestorecheck': 'restore check ok'}
SAFE_BACKUP_REFUSAL = object()
SAFE_BACKUP_MESSAGES = {'not enough host space for a backup', 'not enough VM space for a backup',
                        'backup deferred: heavy lock busy', 'backup deferred: rotation busy',
                        'not enough VM space for a restore check'}


def load_jobs():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import dotenv  # noqa: F401
    except ImportError:  # host python: only labels and schedules are read here; each job's .env is its container's
        import types
        sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: False)
    import install_launchd  # noqa: E402 — the job list itself, unchanged
    return install_launchd.JOBS + EXTRA_JOBS, {**install_launchd.CATCHUP, 'sectorrefresh': {}, 'pgbackup': {}, 'pgrestorecheck': {}}


def _matches(entry, at):
    """launchd StartCalendarInterval: missing keys are wildcards; Weekday 0 and 7 are Sunday."""
    weekday = (at.isoweekday() % 7)  # Sunday 0 … Saturday 6
    wanted = entry.get('Weekday')
    return ((wanted is None or wanted % 7 == weekday)
            and all(entry.get(key) is None or entry[key] == value
                    for key, value in (('Month', at.month), ('Day', at.day), ('Hour', at.hour), ('Minute', at.minute))))


def due_times(schedule, start, end):
    """Run times in [start, end) for one job's schedule (seconds interval, or calendar dict/list)."""
    if isinstance(schedule, int):
        at = start
        while at < end:
            yield at
            at += timedelta(seconds=schedule)
        return
    entries = schedule if isinstance(schedule, list) else [schedule]
    at = start.replace(second=0, microsecond=0)
    if at < start:
        at += timedelta(minutes=1)
    while at < end:
        if any(_matches(entry, at) for entry in entries):
            yield at
        at += timedelta(minutes=1)


def plan(hours, now=None):
    jobs, catchup = load_jobs()
    start = (now or datetime.now(SEOUL)).replace(second=0, microsecond=0)
    end = start + timedelta(hours=hours)
    runs = sorted((at, label) for label, _argv, schedule in jobs for at in due_times(schedule, start, end))
    return runs, {label for label, _argv, _schedule in jobs}, catchup


def run_job(label, log=print):
    """One job (the chain: its steps in order) in one-shot containers; each outcome is recorded in collect_runs."""
    steps = (('chain',) if os.environ.get('COLLECT_CHAIN_INTAKE_ONLY') == '1' else CHAIN_SEQUENCE) if label == 'chain' else (label,)
    for step in steps:
        marker_path = FEED_HOLD if step == 'chain' and os.environ.get('COLLECT_FEED_WORK_VOLUME') else HOLD
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with marker_path.open('x') as marker:
                marker.write(f'{step} {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())} UTC\n')
        except FileExistsError:
            log('collection held: inspect the previous work copy and run before clearing the hold')
            return False
        sync_feed = step == 'chain' and bool(os.environ.get('COLLECT_FEED_WORK_VOLUME')) \
            and os.environ.get('COLLECT_FEED_AUTO_SYNC') == '1'
        if sync_feed:
            import refactor_collect_engine as engine
            # Graph rows the computation paths added to PG first (refactor_feed_graph.py): otherwise the refreshed
            # file issues their IDs again and the publication stops (runs 365, 445).
            try:
                code, output = engine.run(['python', '/app/scripts/refactor_feed_graph.py'], internet=False, limit=600)
            except Exception as exc:  # noqa: BLE001 - nothing changed: the feed stays held
                code, output = 1, f'{type(exc).__name__}: {str(exc)[:200]}'
            if code != 0:
                log(f'feed graph catch-up failed: isolated feed remains held ({output.strip()[-300:]})')
                return False
            log(f'feed graph catch-up: {output.strip().splitlines()[-1] if output.strip() else ""}')
            try:
                refreshed = engine.feed_maintenance('refresh')
            except Exception:  # a failed refresh never changes the shared work copy
                refreshed = False
            if not refreshed:
                log('feed refresh failed: isolated feed remains held')
                return False
        result = _run_one(step, log)
        if result is SAFE_BACKUP_REFUSAL:
            marker_path.unlink()  # the refusal happened before any backup file or work-copy mutation
            log('backup refused for space; collection remains enabled')
            return False  # the backup itself still failed and is recorded as such
        if not result:
            log(f'collection held after {step}: inspect the work copy and run before clearing the hold')
            return False
        if sync_feed:
            try:
                synchronized = engine.feed_maintenance('sync')
            except Exception:
                synchronized = False
            if not synchronized:
                # A PG publication may already exist; prevent stale work from issuing colliding IDs.
                HOLD.touch(exist_ok=True)
                log('feed synchronization failed: collection held for reconciliation')
                return False
        marker_path.unlink()
    return True


def _run_one(label, log=print):
    import refactor_collect_engine as engine
    started = time.monotonic()
    started_utc = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    if label in HOST_JOBS:
        import subprocess
        try:
            done = subprocess.run(HOST_JOBS[label], cwd=ROOT, capture_output=True, text=True, timeout=JOB_SECONDS)
            last = (done.stdout.strip().splitlines() or done.stderr.strip().splitlines() or ['(no output)'])[-1][:300]
            kind = 'applied' if done.returncode == 0 and HOST_OK[label] in done.stdout else 'failed'
        except subprocess.TimeoutExpired:
            last, kind = f'stopped at the {JOB_SECONDS}s limit', 'failed'
        recorded, _ = engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, started_utc, last, kind],
                                 internet=False, limit=300)
        log(f'{label} {kind} {time.monotonic() - started:.0f}s {last}')
        if label in ('pgbackup', 'pgrestorecheck') and kind == 'failed' and last in SAFE_BACKUP_MESSAGES and recorded == 0:
            return SAFE_BACKUP_REFUSAL
        return kind == 'applied'
    feed_env = {}
    if label == 'chain' and os.environ.get('COLLECT_FEED_KEYWORD_ONLY') == '1':
        feed_env = {'COLLECT_MAX_MODEL_CALLS': '0'}
    elif label == 'chain' and os.environ.get('COLLECT_FEED_STRICT_IMAGES') == '1':
        limit = int(os.environ.get('COLLECT_FEED_MODEL_ATTEMPTS', '2'))
        if not 1 <= limit <= 2:
            raise ValueError('Invalid feed model attempt limit')
        feed_env = {'COLLECT_MAX_MODEL_CALLS': str(limit),
                    'COLLECT_MAX_NEW_DOCS': '5' if os.environ.get('COLLECT_FEED_BATCH_MODEL') == '1' else '1'}
    code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', label], job=label,
                              name=f'explorer-collect-{label}-{os.getpid()}', memory=JOB_MEMORY.get(label, '2g'),
                              internet=os.environ.get('NO_INTERNET') != '1', limit=JOB_SECONDS,
                              extra_env={**({'TRIAL_HOST_CAPS': JOB_HOST_CAPS[label]} if label in JOB_HOST_CAPS else {}),
                                         **feed_env,
                                         **JOB_ENV.get(label, {})} or None)
    if code is None:  # stopped at the limit (the container is removed): recorded as failed, nothing applied
        engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, started_utc,
                    f'stopped at the {JOB_SECONDS}s limit'], internet=False, limit=300)
        log(f'{label} stopped at the {JOB_SECONDS}s limit (recorded as failed, nothing applied)')
        return False
    lines = [line for line in output.splitlines() if line.startswith('{')]
    if code != 0 and not lines:
        engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, started_utc,
                    f'job container exited {code} before recording its outcome'], internet=False, limit=300)
    log(f'{label} rc={code} {time.monotonic() - started:.0f}s {lines[-1] if lines else "(no record line)"}')
    try:
        import json
        outcome = json.loads(lines[-1])['outcome'] if lines else ''
        if label in ISOLATED_JOBS:  # nothing of a failed source was published: only 'held back' stops the others
            return code == 0 and outcome.split(':', 1)[0] in ('applied', 'partial', 'failed', 'skipped')
        return code == 0 and (outcome.startswith('applied:') or outcome.startswith('skipped:') or
                              (label == 'usbriefing' and outcome.startswith('partial: US briefing headline failures; ')) or
                              (label == 'pfclose' and outcome in ('partial: portfolio close reported errors',
                                                                  'partial: portfolio close model cap reached')))
    except (ValueError, KeyError, TypeError):
        return False


def catchup_due(enabled, log=print):
    """Enabled calendar jobs whose latest due run has no applied record yet (judged in a one-shot container)."""
    import json
    import refactor_collect_engine as engine
    enabled = catchup_enabled(enabled, datetime.now(SEOUL))
    if not enabled:
        return []
    try:
        code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', '--catchup', ','.join(sorted(enabled))],
                                  internet=False, limit=300)
        lines = [line for line in output.splitlines() if line.startswith('[')]
        return json.loads(lines[-1]) if code == 0 and lines else []
    except (RuntimeError, OSError, ValueError) as exc:
        log(f'catch-up check failed: {exc}')
        return []


def catchup_enabled(enabled, now):
    """Optionally defer catch-up for a named job until its next meaningful scheduled slot."""
    result = set(enabled)
    all_after = os.environ.get('COLLECT_CATCHUP_AFTER')
    if all_after:
        boundary = datetime.fromisoformat(all_after)
        if boundary.tzinfo is None:
            raise ValueError('COLLECT_CATCHUP_AFTER requires a timezone')
        if now < boundary:
            return set()
    for label, key in (('prices', 'COLLECT_PRICES_CATCHUP_AFTER'),
                       ('usbriefing', 'COLLECT_USBRIEFING_CATCHUP_AFTER'),
                       ('krmovers', 'COLLECT_KRMOVERS_CATCHUP_AFTER')):
        after = os.environ.get(key)
        if after:
            boundary = datetime.fromisoformat(after)
            if boundary.tzinfo is None:
                raise ValueError(f'{key} requires a timezone')
            if now < boundary:
                result.discard(label)
    return result


def due_now(jobs, enabled, last, now, next_interval):
    """Labels due in [last, now): calendar entries as launchd matched them, intervals from their own next time."""
    due = []
    for label, _argv, schedule in jobs:
        if label not in enabled:
            continue
        if label == 'observealerts' and os.environ.get('COLLECT_OBSERVE_ALERTS_AFTER'):
            after = datetime.fromisoformat(os.environ['COLLECT_OBSERVE_ALERTS_AFTER'])
            if after.tzinfo is None:
                raise ValueError('COLLECT_OBSERVE_ALERTS_AFTER requires a timezone')
            if now < after:
                continue
        if isinstance(schedule, int):
            if next_interval.setdefault(label, last) <= now:  # launchd runs an interval job once at load
                due.append(label)
                while next_interval[label] <= now:
                    next_interval[label] += timedelta(seconds=schedule)
        elif any(True for _ in due_times(schedule, last, now)):
            due.append(label)
        elif label == 'pgbackup' and os.environ.get('COLLECT_PGBACKUP_PROBE_AT'):
            probe = datetime.fromisoformat(os.environ['COLLECT_PGBACKUP_PROBE_AT'])
            if probe.tzinfo is None:
                raise ValueError('COLLECT_PGBACKUP_PROBE_AT requires a timezone')
            if last <= probe < now:
                due.append(label)
    return due


def wait_ready(log=print, every=30):
    """Until Docker and PG answer and migrations are applied; then job containers left by a stopped scheduler are removed and
    their runs recorded as interrupted (catch-up then counts them as attempts)."""
    import refactor_collect_engine as engine
    while True:
        try:
            engine.call('GET', '/_ping', raw=True, timeout=10)  # Docker (Colima) answers: after a reboot it may start later
            code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', '--ready'], internet=False, limit=120)
            if code == 0:
                break
            log(f'not ready: {output.strip()[-200:]}')
        except (RuntimeError, OSError, ValueError) as exc:
            log(f'not ready: {exc}')
        time.sleep(every)
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    for name, label in engine.orphans():
        engine.remove(name)
        if label:
            engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, now,
                        'cut off (left by a stopped scheduler or a reboot)', 'interrupted'], internet=False, limit=120)
        log(f'removed left-over job container {name}')


def _send_operator(text):
    """One Telegram message to the operator with the collection send credentials; True when Telegram accepted it."""
    import json
    import urllib.request
    import refactor_collect_engine as engine
    found = engine.secrets(engine.SEND_KEYS)
    token, chat = found.get('TELEGRAM_BOT_TOKEN'), found.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return False
    request = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',
                                     data=json.dumps({'chat_id': chat, 'text': text}).encode(),
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200
    except OSError:
        return False


def alert_held_briefing(now=None, log=print, send=_send_operator):
    """While collection stays held after a failure: once a day between 06:20 and the US briefing's 06:30 slot, tell
    the operator that the briefing will not run. It only tells; the hold and the briefing are left to the operator
    (runbook-usbriefing-under-hold.md). A failed send is tried again on the next minute of the window."""
    now = now or datetime.now(SEOUL)
    if not HOLD.exists() or not BRIEFING_ALERT[0] <= (now.hour, now.minute) < BRIEFING_ALERT[1]:
        return False
    day = now.date().isoformat()
    if BRIEFING_ALERT_MARK.exists() and BRIEFING_ALERT_MARK.read_text().strip() == day:
        return False
    held = HOLD.read_text().strip()[:120]
    sent = send(f'[수집 보류] {held}\n06:30 미국장 브리핑이 이대로는 실행되지 않습니다. 보류를 자동으로 풀거나 브리핑을 '
                f'실행하지 않았습니다.\n절차: ~/server-data/review/refactor-single/runbook-usbriefing-under-hold.md')
    if sent:
        BRIEFING_ALERT_MARK.write_text(day)
    log(f'briefing hold alert {"sent" if sent else "not sent"} ({held})')
    return sent


def run_loop(enabled, log=print):
    while HOLD.exists():
        log('collection held: inspect the previous work copy and run before clearing the hold')
        alert_held_briefing(log=log)
        time.sleep(60)
    wait_ready(log)
    jobs, _catchup = load_jobs()
    # time.monotonic() starts near 0 in this process on macOS: start one interval back so catch-up is checked at once
    queue, next_interval, checked = [], {}, -float(CATCHUP_SECONDS)
    last = datetime.now(SEOUL).replace(second=0, microsecond=0)
    while True:
        now = datetime.now(SEOUL)
        due = [label for label in due_now(jobs, enabled, last, now, next_interval) if label not in queue]
        # A job with a set time (the US briefing) goes ahead of anything waiting, catch-up runs included.
        queue = [label for label in due if label in FIRST] + queue + [label for label in due if label not in FIRST]
        last = now
        if not queue and time.monotonic() - checked >= CATCHUP_SECONDS:  # only when idle: no duplicate of a queued run
            checked = time.monotonic()
            queue += [label for label in catchup_due(enabled, log) if label not in queue]
        if queue:
            if not run_job(queue.pop(0), log):
                while HOLD.exists():
                    alert_held_briefing(log=log)
                    time.sleep(60)  # no later job can publish a failed run's partial work
        else:
            time.sleep(TICK_SECONDS)


def check_enabled(labels):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from refactor_collect_job import CONNECTED_SENDS, NEVER, SENDS
    from refactor_collect_job import CHAIN_STEPS
    jobs, _ = load_jobs()
    known = {label for label, _a, _s in jobs} | set(CHAIN_STEPS)
    unknown, refused = labels - known, labels & ((SENDS - CONNECTED_SENDS) | NEVER)
    if unknown or refused:
        raise SystemExit(f'Not enabled — unknown: {sorted(unknown)}, refused (sends/backfill): {sorted(refused)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=float, help='hours ahead to list (nothing is run)')
    parser.add_argument('--run', action='store_true', help='run the enabled jobs on their schedule')
    parser.add_argument('--enable', default='', help='comma-separated job labels to run (none by default)')
    parser.add_argument('--once', help='with --run: run this enabled job once now, then exit')
    args = parser.parse_args()
    if args.run:
        enabled = {label for label in args.enable.split(',') if label}
        if not enabled:
            raise SystemExit('Nothing enabled: name the jobs with --enable (activation is at the cutover)')
        check_enabled(enabled)
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        lock = open(LOCK, 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another scheduler holds the lock (single writer)') from None
        if args.once:
            if args.once not in enabled:
                raise SystemExit(f'{args.once} is not enabled')
            if not run_job(args.once):
                raise SystemExit(1)
            return
        return run_loop(enabled)
    if args.plan is None:
        parser.error('--plan or --run is required')
    runs, labels, catchup = plan(args.plan)
    counts = Counter(label for _at, label in runs)
    for at, label in runs:
        print(at.strftime('%m-%d %a %H:%M'), label, '(catchup)' if label in catchup else '')
    print(f'{len(runs)} runs of {len(counts)} jobs in {args.plan}h; idle jobs in this window: '
          f'{sorted(labels - set(counts))}')


if __name__ == '__main__':
    main()

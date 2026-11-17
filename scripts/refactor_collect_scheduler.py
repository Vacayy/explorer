"""Mac mini collection schedule (single writer).

Reads the MacBook's launchd job list as it is (scripts/install_launchd.py JOBS and its CATCHUP rules) and runs
when each job would run, in Asia/Seoul time as launchd did on the MacBook.

--plan lists the run times; nothing is executed.
--run executes only the jobs named in --enable, one at a time (a run started while another runs waits in a
queue; repeats of a waiting job coalesce, as launchd does), each as a one-shot container
(scripts/refactor_collect_trial.sh job <label> → scripts/refactor_collect_job.py, per-host request cap, record
in PG collect_runs). A file lock keeps a second scheduler from starting. Sending jobs and the overnight backfill
are refused. Missed runs are caught up as on the MacBook (pipeline.catchup over collect_runs, checked at start
and every 30 minutes while idle). Before the cutover the job target is the disposable clone schema only; the MacBook stays the
collection source until then, so nothing is enabled by default.

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
JOB_SECONDS = int(os.environ.get('COLLECT_JOB_SECONDS', '3600'))  # one job's time limit (the MacBook chain step limit)
TICK_SECONDS = 20
JOB_MEMORY = {'proposals': '3584m'}  # measured peak 2.9GiB (weekly); every other job 2g
# The MacBook's 30-minute chain (scripts/run_chain.sh) in its order: one container per step, each recorded; a step
# that fails does not stop the next (as there). Not here: probe_llm (the gate does it), briefing catch-up (sends),
# vault export and the search index (the projection builder). Image backfill runs with at most 10 calls.
CHAIN_SEQUENCE = ('chain_macro_news', 'chain', 'chain_causal', 'chain_signals', 'chain_narratives', 'chain_events',
                  'chain_images', 'chain_actions', 'chain_digests')
# Per-run host caps of the intake (PM 6938365215, 6940286658): ~30 Naver blog feeds, 32 Telegram channel pages,
# 25 YouTube channel feeds plus captions, Telegram images read within the 30-minute image budget (numbered CDN hosts).
JOB_HOST_CAPS = {'chain': 'rss.blog.naver.com=40,t.me=40,www.youtube.com=40,.telesco.pe=40',
                 # one chart request per listed code (3,017 now), retries counted in the same cap (PM 6942746227)
                 'history': 'fchart.stock.naver.com=3200',
                 # credit (macbook-source #3 6942831447): 34 companies — issuer scan and history on the scanner host,
                 # symbol search as the fallback, 10 Treasury series from FRED; any other host keeps the default 20
                 'credit': 'scanner.tradingview.com=150,symbol-search.tradingview.com=60,fred.stlouisfed.org=12',
                 # peer: one daily-price page per catalog company (104 now)
                 'peer': 'stock.naver.com=120',
                 # US briefing: macro series from FRED (three tries when all fail), Yahoo quotes·charts·headlines for the
                 # indices, macro proxies and the movers; newswire feeds keep the default 20
                 'usbriefing': 'fred.stlouisfed.org=40,.finance.yahoo.com=150'}
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
              ('pgbackup', ['scripts/refactor_pg_backup.sh', 'backup'], {'Hour': 4, 'Minute': 30}),
              ('pgrestorecheck', ['scripts/refactor_pg_backup.sh', 'check'], {'Weekday': 0, 'Hour': 5, 'Minute': 0})]
# Jobs that need the host's docker CLI (the backup execs into the PG container), run here instead of in a job container;
# recorded in collect_runs like the others. A restore check counts only when it says every row count is equal.
HOST_JOBS = {'pgbackup': ('sh', '-c', 'scripts/refactor_pg_backup.sh backup'),
             'pgrestorecheck': ('sh', '-c', 'scripts/refactor_pg_backup.sh check "$(ls -t "$HOME"/server-data/backups/refactor-pg/'
                                            '*-candidate.dump | head -1)"')}
HOST_OK = {'pgbackup': '-candidate.dump', 'pgrestorecheck': 'restore check ok'}


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
    for step in (CHAIN_SEQUENCE if label == 'chain' else (label,)):
        _run_one(step, log)


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
        engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, started_utc, last, kind],
                   internet=False, limit=300)
        log(f'{label} {kind} {time.monotonic() - started:.0f}s {last}')
        return
    code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', label], job=label,
                              name=f'explorer-collect-{label}-{os.getpid()}', memory=JOB_MEMORY.get(label, '2g'),
                              internet=os.environ.get('NO_INTERNET') != '1', limit=JOB_SECONDS,
                              extra_env={**({'TRIAL_HOST_CAPS': JOB_HOST_CAPS[label]} if label in JOB_HOST_CAPS else {}),
                                         **JOB_ENV.get(label, {})} or None)
    if code is None:  # stopped at the limit (the container is removed): recorded as failed, nothing applied
        engine.run(['python', '/app/scripts/refactor_collect_job.py', '--stopped', label, started_utc,
                    f'stopped at the {JOB_SECONDS}s limit'], internet=False, limit=300)
        log(f'{label} stopped at the {JOB_SECONDS}s limit (recorded as failed, nothing applied)')
        return
    lines = [line for line in output.splitlines() if line.startswith('{')]
    log(f'{label} rc={code} {time.monotonic() - started:.0f}s {lines[-1] if lines else "(no record line)"}')


def catchup_due(enabled, log=print):
    """Enabled calendar jobs whose latest due run has no applied record yet (judged in a one-shot container)."""
    import json
    import refactor_collect_engine as engine
    try:
        code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', '--catchup', ','.join(sorted(enabled))],
                                  internet=False, limit=300)
        lines = [line for line in output.splitlines() if line.startswith('[')]
        return json.loads(lines[-1]) if code == 0 and lines else []
    except (RuntimeError, OSError, ValueError) as exc:
        log(f'catch-up check failed: {exc}')
        return []


def due_now(jobs, enabled, last, now, next_interval):
    """Labels due in [last, now): calendar entries as launchd matched them, intervals from their own next time."""
    due = []
    for label, _argv, schedule in jobs:
        if label not in enabled:
            continue
        if isinstance(schedule, int):
            if next_interval.setdefault(label, last) <= now:  # launchd runs an interval job once at load
                due.append(label)
                while next_interval[label] <= now:
                    next_interval[label] += timedelta(seconds=schedule)
        elif any(True for _ in due_times(schedule, last, now)):
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


def run_loop(enabled, log=print):
    wait_ready(log)
    jobs, _catchup = load_jobs()
    queue, next_interval, checked = [], {}, 0.0
    last = datetime.now(SEOUL).replace(second=0, microsecond=0)
    while True:
        now = datetime.now(SEOUL)
        queue += [label for label in due_now(jobs, enabled, last, now, next_interval) if label not in queue]
        last = now
        if not queue and time.monotonic() - checked >= CATCHUP_SECONDS:  # only when idle: no duplicate of a queued run
            checked = time.monotonic()
            queue += [label for label in catchup_due(enabled, log) if label not in queue]
        if queue:
            run_job(queue.pop(0), log)  # concurrency 1: the next waits for this one
        else:
            time.sleep(TICK_SECONDS)


def check_enabled(labels):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from refactor_collect_job import NEVER, SENDS
    from refactor_collect_job import CHAIN_STEPS
    jobs, _ = load_jobs()
    known = {label for label, _a, _s in jobs} | set(CHAIN_STEPS)
    unknown, refused = labels - known, labels & (SENDS | NEVER)
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
            return run_job(args.once)
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

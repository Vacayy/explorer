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
# image backfill (its own budget, not connected), vault export and the search index (the projection builder).
CHAIN_SEQUENCE = ('chain_macro_news', 'chain', 'chain_causal', 'chain_signals', 'chain_narratives', 'chain_events',
                  'chain_actions', 'chain_digests')
JOB_HOST_CAPS = {'chain': 'rss.blog.naver.com=40'}  # ~30 registered Naver blog feeds per run (PM 6938365215)
CATCHUP_SECONDS = 1800  # the MacBook's catchup job ran every 30 minutes


def load_jobs():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import dotenv  # noqa: F401
    except ImportError:  # host python: only labels and schedules are read here; each job's .env is its container's
        import types
        sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: False)
    import install_launchd  # noqa: E402 — the job list itself, unchanged
    return install_launchd.JOBS, install_launchd.CATCHUP


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
    code, output = engine.run(['python', '/app/scripts/refactor_collect_job.py', label], job=label,
                              name=f'explorer-collect-{label}-{os.getpid()}', memory=JOB_MEMORY.get(label, '2g'),
                              internet=os.environ.get('NO_INTERNET') != '1', limit=JOB_SECONDS,
                              extra_env={'TRIAL_HOST_CAPS': JOB_HOST_CAPS[label]} if label in JOB_HOST_CAPS else None)
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
    """Until PG answers and migrations are applied; then job containers left by a stopped scheduler are removed and
    their runs recorded as interrupted (catch-up then counts them as attempts)."""
    import refactor_collect_engine as engine
    while True:
        try:
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

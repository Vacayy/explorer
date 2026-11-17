"""Mac mini collection schedule (single writer).

Reads the MacBook's launchd job list as it is (scripts/install_launchd.py JOBS and its CATCHUP rules) and runs
when each job would run, in Asia/Seoul time as launchd did on the MacBook.

--plan lists the run times; nothing is executed.
--run executes only the jobs named in --enable, one at a time (a run started while another runs waits in a
queue; repeats of a waiting job coalesce, as launchd does), each as a one-shot container
(scripts/refactor_collect_trial.sh job <label> → scripts/refactor_collect_job.py, per-host request cap, record
in PG collect_runs). A file lock keeps a second scheduler from starting. Sending jobs and the overnight backfill
are refused. Before the cutover the job target is the disposable clone schema only; the MacBook stays the
collection source until then, so nothing is enabled by default.

  python scripts/refactor_collect_scheduler.py --plan 24                       # the next 24 hours
  python scripts/refactor_collect_scheduler.py --run --enable indexintraday    # loop
  python scripts/refactor_collect_scheduler.py --run --enable prices --once prices   # one run now, then exit
"""
import argparse
import fcntl
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parent.parent
LOCK = Path(os.environ.get('COLLECT_SCHEDULER_LOCK', Path.home() / 'server-data/review/refactor-single/collect-scheduler.lock'))
JOB_SECONDS = int(os.environ.get('COLLECT_JOB_SECONDS', '3600'))  # one job's time limit (the MacBook chain step limit)
TICK_SECONDS = 20


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
    """One job in its one-shot container; the job harness records the outcome in collect_runs."""
    started = time.monotonic()
    try:
        done = subprocess.run([str(ROOT / 'scripts/refactor_collect_trial.sh'), 'job', label], capture_output=True,
                              text=True, timeout=JOB_SECONDS)
        lines = [line for line in done.stdout.splitlines() if line.startswith('{')]
        log(f'{label} rc={done.returncode} {time.monotonic() - started:.0f}s {lines[-1] if lines else "(no record line)"}')
    except subprocess.TimeoutExpired:
        log(f'{label} stopped at the {JOB_SECONDS}s limit')


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


def run_loop(enabled, log=print):
    jobs, _catchup = load_jobs()
    queue, next_interval = [], {}
    last = datetime.now(SEOUL).replace(second=0, microsecond=0)
    while True:
        now = datetime.now(SEOUL)
        queue += [label for label in due_now(jobs, enabled, last, now, next_interval) if label not in queue]
        last = now
        if queue:
            run_job(queue.pop(0), log)  # concurrency 1: the next waits for this one
        else:
            time.sleep(TICK_SECONDS)


def check_enabled(labels):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from refactor_collect_job import NEVER, SENDS
    jobs, _ = load_jobs()
    known = {label for label, _a, _s in jobs}
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

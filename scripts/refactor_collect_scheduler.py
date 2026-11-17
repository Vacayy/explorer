"""Mac mini collection schedule (single writer) — plan mode only for now.

Reads the MacBook's launchd job list as it is (scripts/install_launchd.py JOBS and its CATCHUP rules) and lists
when each job would run, in Asia/Seoul time as launchd did on the MacBook. Nothing is executed: running jobs
(one-shot collector containers, the collector bridge) is enabled only at cutover, while the MacBook stays the
collection source until then.

  python scripts/refactor_collect_scheduler.py --plan 24      # the next 24 hours
"""
import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo('Asia/Seoul')


def load_jobs():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=float, required=True, help='hours ahead to list (nothing is run)')
    args = parser.parse_args()
    runs, labels, catchup = plan(args.plan)
    counts = Counter(label for _at, label in runs)
    for at, label in runs:
        print(at.strftime('%m-%d %a %H:%M'), label, '(catchup)' if label in catchup else '')
    print(f'{len(runs)} runs of {len(counts)} jobs in {args.plan}h; idle jobs in this window: '
          f'{sorted(labels - set(counts))}')


if __name__ == '__main__':
    main()

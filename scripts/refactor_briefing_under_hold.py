"""The US briefing alone while collection is held (runbook-usbriefing-under-hold.md). Never clears the hold for good.

  python3 scripts/refactor_briefing_under_hold.py check    # read only: what the briefing would publish besides its own rows
  python3 scripts/refactor_briefing_under_hold.py run      # after a 'safe' check, or a 'review' an operator accepted

check (in a one-shot container, no internet): the briefing replaces its tables in PG with the shared collector file's
rows, so every difference between that file and PG in those tables goes out with it. Verdict:
  safe    no difference: only the briefing's own writes will be published
  stop    anything else (a table differs, or PG has rows the file lacks: the briefing would delete them)
(review, for job_runs failure records, no longer arises: job_runs is published by id, this run's records only.)

run (on the host): stops the scheduler, moves the hold aside, runs the briefing once as the scheduler would, then
puts the hold back whatever happened (a failed run's own hold marker is kept beside it as evidence) and restarts
the scheduler only after the hold is confirmed back.
"""
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

# job_runs is not among them: since the keyed publication only the briefing's own records go out (refactor_collect_job
# .new_job_runs), so records a failed run left in the file cannot ride along.
BRIEFING_TABLES = ('cache_meta', 'macro_news', 'macro_signals', 'market_indicators', 'us_briefings',
                   'us_macro_issues', 'us_movers', 'us_ticker_news')
FAILURE = ('error', 'failed')
ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get('BRIEFING_HOLD_DIR', Path.home() / 'server-data/review/refactor-single'))
PLIST = Path(os.environ.get('BRIEFING_SCHEDULER_PLIST',
                            Path.home() / 'Library/LaunchAgents/dev.explorer.refactor-collect-scheduler.plist'))
LAUNCHCTL = os.environ.get('BRIEFING_LAUNCHCTL', 'launchctl')
SERVICE = 'dev.explorer.refactor-collect-scheduler'


def _digest(row):
    return hashlib.sha1(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def compare(pg, work):
    """{table: {work_only, pg_only}} and the job_runs rows only the collector file has."""
    found, extra_runs = {}, []
    for table in BRIEFING_TABLES:
        cursor = work.execute(f'SELECT * FROM "{table}"')
        names = [d[0] for d in cursor.description]
        local = {}
        for values in cursor:
            row = dict(zip(names, values))
            local[_digest(row)] = row
        remote = {_digest(row) for (row,) in pg.execute(
            'SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s', (table,))}
        work_only = [row for key, row in local.items() if key not in remote]
        found[table] = {'work_only': len(work_only), 'pg_only': len(remote - set(local))}
        if table == 'job_runs':
            extra_runs = sorted(work_only, key=lambda r: r.get('id') or 0)
    return found, extra_runs


def readers(job):
    """Code lines that read job_runs records of `job` (for the operator's review)."""
    out = []
    for base in (ROOT / 'backend', ROOT / 'scripts'):
        for path in base.rglob('*.py'):
            if 'test' in path.name:
                continue
            for number, line in enumerate(path.read_text(errors='ignore').splitlines(), 1):
                if 'job_runs' in line and (f"'{job}'" in line or f'"{job}"' in line):
                    out.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()[:160]}')
    return out


def verdict(found, extra_runs):
    if any(n['pg_only'] for n in found.values()):
        return 'stop', 'PG has rows the collector file lacks: the briefing would delete them'
    others = [t for t, n in found.items() if t != 'job_runs' and n['work_only']]
    if others:
        return 'stop', f'other tables differ: {others}'
    if not extra_runs:
        return 'safe', 'only the briefing\'s own rows will be published'
    if any(r.get('status') not in FAILURE for r in extra_runs):
        return 'stop', 'a non-failure job record would be published'
    return 'review', 'only failure records of job_runs would go out with the briefing'


def check():
    import sqlite3
    sys.path.insert(0, str(ROOT / 'scripts'))
    import refactor_collect_trial as trial
    work = sqlite3.connect(f'file:{trial.WORK}?mode=ro', uri=True)
    found, extra_runs = compare(trial._pg(), work)
    kind, why = verdict(found, extra_runs)
    report = {'verdict': kind, 'why': why, 'tables': found,
              'job_runs_extra': [{k: r.get(k) for k in ('id', 'job', 'status', 'ran_at', 'summary')} for r in extra_runs],
              'readers': {job: readers(job) for job in sorted({r.get('job') for r in extra_runs})}}
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return kind


def _scheduler_env():
    plist = plistlib.loads(PLIST.read_bytes())
    return plist, {**os.environ, **plist['EnvironmentVariables']}


def run_once(log):
    """The scheduler's own --once path with the plist's environment and enabled jobs; returns its exit code."""
    plist, env = _scheduler_env()
    argv = plist['ProgramArguments'] + ['--once', 'usbriefing']
    with open(log, 'a') as out:
        return subprocess.run(argv, cwd=plist['WorkingDirectory'], env=env, stdout=out, stderr=subprocess.STDOUT).returncode


def run(runner=run_once):
    hold = STATE / 'collect-scheduler.hold'
    log = STATE / 'logs/collect-scheduler.log'
    if not hold.exists():
        raise SystemExit('No hold: the scheduler runs the briefing itself')
    original = hold.read_text()
    stamp = time.strftime('%Y%m%dT%H%M%S')
    aside = STATE / f'collect-scheduler.hold-aside-{stamp}'

    def note(text):
        with open(log, 'a') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} manual: {text}\n')
    subprocess.run([LAUNCHCTL, 'bootout', f'gui/{os.getuid()}/{SERVICE}'], check=False)
    note(f'scheduler stopped for a single usbriefing run under the hold ({original.strip()[:80]})')
    os.replace(hold, aside)
    code = None
    try:
        code = runner(log)
    finally:
        if hold.exists():  # the failed run's own marker: kept as evidence, the original hold goes back in place
            os.replace(hold, STATE / f'collect-scheduler.hold-usbriefing-failed-{stamp}')
        os.replace(aside, hold)
    if not hold.exists() or hold.read_text() != original:
        note('hold NOT restored: scheduler left stopped')
        raise SystemExit('The hold could not be confirmed back in place; the scheduler stays stopped')
    note(f'usbriefing single run exit {code}; hold restored; scheduler restarted')
    subprocess.run([LAUNCHCTL, 'bootstrap', f'gui/{os.getuid()}', str(PLIST)], check=True)
    return code


if __name__ == '__main__':
    if sys.argv[1:] == ['check']:
        if os.path.exists('/.dockerenv'):
            check()
        else:  # from the host: in a one-shot job container without internet, as the scheduler's checks run
            plist, env = _scheduler_env()
            os.environ.update(plist['EnvironmentVariables'])
            sys.path.insert(0, str(ROOT / 'scripts'))
            import refactor_collect_engine as engine
            code, output = engine.run(['python', '/app/scripts/refactor_briefing_under_hold.py', 'check'],
                                      internet=False, limit=600)
            print(output)
            sys.exit(code or 0)
    elif sys.argv[1:] == ['run']:
        sys.exit(0 if run() == 0 else 1)
    else:
        raise SystemExit(__doc__)

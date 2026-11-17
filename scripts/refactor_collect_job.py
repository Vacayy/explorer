"""One scheduled collection job, run by the Mac mini scheduler in a one-shot container (single writer).

Same safeguards as the isolated trial (scripts/refactor_collect_trial.py): source requests counted per host, a
403/429 or a host reaching TRIAL_MAX_REQUESTS aborts with nothing applied, and collect → check → apply is one
function. Every run, whatever its outcome, is recorded in PG collect_runs. Before the cutover the target is the
disposable clone schema only (the trial's guard refuses the live candidate schema).

Refused here, whatever the scheduler asks: jobs that send (Telegram) and the uncapped overnight tagging backfill.
Jobs not connected yet are recorded as 'unsupported' and not run.

  python scripts/refactor_collect_job.py <label>
  python scripts/refactor_collect_job.py --catchup <label,...>   # which of these to catch up now (prints JSON)
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
TABLE_JOBS = {'prices', 'twrevenue', 'indexintraday'}  # trial.job_table: script → supplement replacement


def run(label):
    from pipeline import llm, postgres_collect_runs, postgres_llm_calls
    pg = trial._pg()
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    entry = {}
    if label in SENDS or label in NEVER:
        outcome = f'refused: {"sends messages" if label in SENDS else "uncapped model calls"}'
    elif label not in TABLE_JOBS:
        outcome = 'unsupported: not connected to the candidate yet'
    else:
        postgres_llm_calls.install(llm, trial._pg)
        trial._instrument()
        trial._point_legacy_at_work()
        try:
            argv, record, tables = trial.job_table(label)
            os.chdir('/app')
            trial._run_script(*argv)
            if record:
                trial._job_record(record, started)
            entry['applied'] = trial._apply_supplement(pg, tables)
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


if __name__ == '__main__':
    if sys.argv[1] == '--catchup':
        catchup(set(sys.argv[2].split(',')))
    else:
        run(sys.argv[1])

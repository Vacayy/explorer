"""Sync rehearsal R3: the operator's personal records against the MacBook's latest copy (pipeline.postgres_record_reimport).

  python /app/scripts/refactor_rehearsal_r3.py           # compare only: counts and conflicting keys (no content)
  python /app/scripts/refactor_rehearsal_r3.py --apply   # then apply (inside the freeze, right after R2), and compare again
Runs on the rehearsal schema only (REFACTOR_FIXTURE_SCHEMA).
"""
import json
import os
import sqlite3
import sys
import time

import psycopg

from pipeline import postgres_record_reimport as reimport

SOURCE, BASE = '/rehearsal/source.db', '/base/stock_explorer.db'


def summary(report):
    totals = {n: sum(r[n] for r in report.values()) for n in ('same', 'take_source', 'keep_candidate', 'conflict')}
    return {'totals': totals, 'ledgers': {k: {n: r[n] for n in ('take_source', 'keep_candidate', 'conflict') if r[n]}
                                          for k, r in report.items() if r['take_source'] or r['keep_candidate'] or r['conflict']},
            'conflicts': {k: r['conflicts'] for k, r in report.items() if r['conflicts']}}


def main():
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    if schema == os.environ.get('TRIAL_LIVE_SCHEMA') and os.environ.get('REFACTOR_T0') != 'live':
        raise SystemExit('The rehearsal schema, never the live one (the cutover itself sets REFACTOR_T0=live)')
    base = sqlite3.connect(f'file:{BASE}?mode=ro&immutable=1', uri=True)
    source = sqlite3.connect(f'file:{SOURCE}?mode=ro', uri=True)
    with psycopg.connect(dsn, options=f'-c search_path={schema}') as pg:
        out = {'before': summary(reimport.compare(pg, base, source))}
        if '--apply' in sys.argv[1:]:
            started = time.monotonic()
            out['applied'] = reimport.apply(pg, base, source)
            out['apply_seconds'] = round(time.monotonic() - started, 1)
            out['after'] = summary(reimport.compare(pg, base, source))
            out['rerun'] = reimport.apply(pg, base, source)
            # R3b: the user's own records made on the MacBook after the base (conversations, questions, studies, boards).
            from pipeline import postgres_user_records_import as user_records
            from pipeline.postgres_principals import operator_principal
            operator = operator_principal(pg)
            started = time.monotonic()
            out['r3b'] = user_records.apply(pg, base, source, operator=operator)
            out['r3b_seconds'] = round(time.monotonic() - started, 1)
            out['r3b_rerun'] = user_records.apply(pg, base, source, operator=operator)
            started = time.monotonic()
            out['requested'] = user_records.apply_requested(pg, base, source)
            out['requested_seconds'] = round(time.monotonic() - started, 1)
            out['requested_rerun'] = user_records.apply_requested(pg, base, source)
            started = time.monotonic()
            out['alert_state'] = user_records.replace_alert_state(pg, source)
            out['alert_state_seconds'] = round(time.monotonic() - started, 1)
            out['alert_state_rerun'] = user_records.replace_alert_state(pg, source)
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == '__main__':
    sys.exit(main())

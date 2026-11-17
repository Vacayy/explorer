"""Collection run record of the Mac mini scheduler (scripts/refactor_collect_scheduler.py) on the candidate PG schema.

One row per scheduled job run, whatever its outcome: applied, partial (some sources failed, the rest applied),
skipped (the job's own admin flag is off, counted as done like the MacBook's 'skipped'),
held back, aborted at a source's block or request cap, failed, refused (a sending or uncapped job) or unsupported
(not connected yet). The scheduler's catch-up reads it the way the MacBook read job_runs `sched:<label>`
(pipeline.catchup): 'applied' counts as done, 'partial' as the MacBook's partial.
Collected text is never stored here, only counts.
"""
import json

from pipeline.postgres_graph_fixture import _guard

NOW = "to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')"


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS collect_runs (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,'
                     'label TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT NOT NULL DEFAULT ' + NOW + ','
                     "outcome TEXT NOT NULL,detail TEXT,requests_json TEXT NOT NULL DEFAULT '{}',model_calls INTEGER,"
                     "result_json TEXT NOT NULL DEFAULT '{}')")
        conn.execute('CREATE INDEX IF NOT EXISTS collect_runs_label ON collect_runs(label,started_at)')


def outcome_kind(outcome):
    """'applied: …'/'held back: …' → the leading word(s) before the colon."""
    return outcome.split(':', 1)[0]


def record(conn, label, started, outcome, *, requests=None, model_calls=None, result=None):
    kind, _, detail = outcome.partition(': ')
    return conn.execute('INSERT INTO collect_runs (label,started_at,outcome,detail,requests_json,model_calls,result_json) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                        (label, started, kind, detail[:500] or None, json.dumps(requests or {}), model_calls,
                         json.dumps(result or {}, ensure_ascii=False, default=str)[:4000])).fetchone()[0]


def runs(conn, label, since):
    """(status, started_at) of a label since a UTC time, in the catch-up module's terms ('ok' = applied)."""
    return [({'applied': 'ok'}.get(outcome, outcome), started) for outcome, started in conn.execute(
        'SELECT outcome,started_at FROM collect_runs WHERE label=%s AND started_at >= %s ORDER BY started_at',
        (label, since))]

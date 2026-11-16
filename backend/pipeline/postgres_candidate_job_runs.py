"""Run records the candidate itself makes (single-path preview), kept apart from the collected `job_runs`.

A legacy computation that records its run (`ops.record_run`) and reads those records back for its cooldown
and budget (the big-picture rebuild) runs on a writable TEMP copy of `job_runs`. The rows it added are kept
here under their own uuid, never with a `job_runs` id, so they cannot collide with the collector's ids; each
projection build appends them to `job_runs` after the collected rows with fresh ids.
"""
from pipeline.postgres_graph_fixture import _guard

COLUMNS = ('job', 'status', 'summary', 'duration_ms', 'ran_at')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('candidate_job_runs')").fetchone()[0] is not None:
            raise ValueError('Candidate job runs already initialized')
        conn.execute('CREATE TABLE candidate_job_runs (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),job TEXT NOT NULL,'
                     'status TEXT NOT NULL,summary TEXT,duration_ms BIGINT,ran_at TEXT NOT NULL,'
                     'created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        conn.execute('CREATE TRIGGER legacy_projection_bump AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE '
                     'ON candidate_job_runs FOR EACH STATEMENT EXECUTE FUNCTION legacy_projection_bump()')


def derive(root, pg):
    """Append the candidate's run records to the projection's job_runs (fresh ids after the collected rows)."""
    if pg.execute("SELECT to_regclass('candidate_job_runs')").fetchone()[0] is None:
        return
    root.executemany(f'INSERT INTO job_runs ({",".join(COLUMNS)}) VALUES ({",".join("?" for _ in COLUMNS)})',
                     pg.execute(f'SELECT {",".join(COLUMNS)} FROM candidate_job_runs ORDER BY ran_at,created_at').fetchall())


def floor(conn):
    return conn.execute('SELECT COALESCE(max(id),0) FROM temp.job_runs').fetchone()[0]


def capture(pg, conn, start, source):
    """Keep the rows a request added to its TEMP job_runs (ids above `start`); returns their count."""
    from pipeline.postgres_owner_overrides import record_outputs
    rows = conn.execute(f'SELECT {",".join(COLUMNS)} FROM temp.job_runs WHERE id > ? ORDER BY id', (start,)).fetchall()
    keys = [pg.execute(f'INSERT INTO candidate_job_runs ({",".join(COLUMNS)}) VALUES ({",".join("%s" for _ in COLUMNS)}) '
                       'RETURNING id', tuple(row)).fetchone()[0] for row in rows]
    if keys:
        record_outputs(pg, source, [('candidate_job_runs', key) for key in keys])
    return len(keys)

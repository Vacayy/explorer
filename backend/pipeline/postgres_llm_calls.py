"""Model call record (llm_calls) on the candidate PG schema: the single basis of cost observation.

Every model call passes llm._execute, whose call observer writes this ledger whatever recorder the caller passed
(feature records such as chat_model_calls stay as they are), on its own connection, outside the request's
transaction; a failure is only logged (the legacy meaning).
No prompt or output is stored. Each row also keeps who called (a principal id, 'operator', 'trial' or 'anon')
and the usage reservation, so costs can be matched to the usage gate. Rows older than 90 days are pruned (daily).
"""
import logging

from pipeline.postgres_graph_fixture import _guard

log = logging.getLogger(__name__)
RETENTION_DAYS = 90
COLUMNS = ('job', 'model', 'engine', 'effort', 'input_tokens', 'cache_create_tokens', 'cache_read_tokens',
           'output_tokens', 'thinking_tokens', 'cost_usd', 'duration_ms', 'ok', 'error', 'principal', 'reservation_id')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute("CREATE TABLE IF NOT EXISTS llm_calls (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,job TEXT,model TEXT,"
                     "engine TEXT,effort TEXT,input_tokens INTEGER,cache_create_tokens INTEGER,cache_read_tokens INTEGER,"
                     "output_tokens INTEGER,thinking_tokens INTEGER,cost_usd DOUBLE PRECISION,duration_ms INTEGER,"
                     "ok INTEGER NOT NULL DEFAULT 1,error TEXT,principal TEXT,reservation_id TEXT,"
                     "created_at TEXT NOT NULL DEFAULT to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS'))")
        conn.execute('CREATE INDEX IF NOT EXISTS llm_calls_job ON llm_calls(job,created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS llm_calls_created ON llm_calls(created_at)')


def _caller():
    """(principal, reservation id) of the current call: a signed-in member's id, 'trial', 'anon' or 'operator'."""
    from pipeline.postgres_principals import request_principal
    from pipeline.postgres_usage_gate import usage
    context = usage.get()
    principal = request_principal.get()
    if principal is None:
        principal = 'operator' if context is None or context.role == 'operator' else (context.role or 'anon')
    return principal, (context.reservation if context is not None else None)


def install(llm_module, connect):
    """Record every model call of this process here (llm.call_observer; `connect` opens a new connection per record)."""
    import time
    pruned = [0.0]

    def record(job, model, engine, effort, res, duration_ms, err):
        try:
            usage = (res.usage if res else {}) or {}
            principal, reservation = _caller()
            with connect() as conn:
                conn.execute(f'INSERT INTO llm_calls ({",".join(COLUMNS)}) VALUES ({",".join(["%s"] * len(COLUMNS))})',
                             (job or None, model, engine, effort, usage.get('input'), usage.get('cache_create'),
                              usage.get('cache_read'), usage.get('output'), usage.get('thinking'),
                              res.cost_usd if res else None, duration_ms, 1 if err is None else 0,
                              None if err is None else str(err)[:300], principal, reservation))
                if time.monotonic() - pruned[0] > 86400:  # at most once a day per process
                    prune(conn)
                    pruned[0] = time.monotonic()
        except Exception:  # noqa: BLE001 - recording never breaks the call it records
            log.warning('llm_calls record failed', exc_info=True)
    llm_module.call_observer = record


def prune(conn):
    return conn.execute("DELETE FROM llm_calls WHERE created_at < to_char(timezone('utc',now()) - %s * interval '1 day',"
                        "'YYYY-MM-DD HH24:MI:SS')", (RETENTION_DAYS,)).rowcount

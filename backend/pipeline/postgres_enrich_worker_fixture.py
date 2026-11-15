"""Explicit enrichment callback for disposable fixtures; no model is invoked here."""
from pipeline.postgres_graph_fixture import _guard, finish_with_graph
from pipeline.postgres_ingest_fixture import claim_enrichment, fail_enrichment
from functools import partial
import math
from psycopg.types.json import Jsonb


def fixture_call_recorder(factory, *, attempt_token=None):
    """Record bounded usage metadata only, never prompts, responses or errors."""
    def record(task, model, engine, effort, result, duration_ms, error):
        usage = (result.usage or {}) if result is not None else {}
        safe_usage = {key:value for key,value in usage.items()
                      if key in {'input','output','cache_create','cache_read','thinking'}
                      and isinstance(value,int) and not isinstance(value,bool) and value >= 0}
        cost = result.cost_usd if result is not None else None
        if not isinstance(cost,(int,float)) or isinstance(cost,bool) or not math.isfinite(cost) or cost < 0:
            cost = None
        with factory() as conn:
            _guard(conn)
            conn.execute('INSERT INTO ingest_llm_calls(task,model,engine,effort,duration_ms,ok,usage,cost_usd,attempt_token) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (task,model,engine,effort,duration_ms,error is None,Jsonb(safe_usage),cost,attempt_token))
    return record


def validate_enricher(callback):
    """Reject passing the legacy function without an explicit provider."""
    from pipeline.enrich import enrich
    if callback is enrich:
        raise ValueError('Existing enrichment requires an explicit vocabulary provider')
    if isinstance(callback, partial) and callback.func is enrich:
        raise ValueError('Existing enrichment requires an explicit vocabulary provider and attempt recorder')


def recover_cycle_attempts(conn):
    """Caller must hold the cycle lock throughout this transaction."""
    _guard(conn)
    conn.execute("UPDATE ingest_enrichment_jobs j SET status='unknown',token=NULL,worker_id=NULL,started_at=NULL "
                 "FROM ingest_enrichment_attempts a WHERE j.token=a.token AND j.status='running' "
                 "AND j.worker_id LIKE 'cycle:%' AND a.external AND a.state='started'")
    conn.execute("UPDATE ingest_enrichment_attempts SET state='unknown',finished_at=clock_timestamp() "
                 "WHERE external AND state='started' AND worker_id LIKE 'cycle:%' AND token NOT IN "
                 "(SELECT token FROM ingest_enrichment_jobs WHERE status='running' AND token IS NOT NULL)")
    conn.execute("UPDATE ingest_enrichment_jobs SET status='failed',token=NULL,worker_id=NULL,started_at=NULL "
                 "WHERE status='running' AND worker_id LIKE 'cycle:%'")


def existing_enricher(factory, *, record_call=None):
    """Use the existing single-document enrichment with this fixture's graph."""
    from pipeline.enrich import enrich
    from pipeline.postgres_enrich_vocabulary_fixture import vocabulary_provider
    provider = vocabulary_provider(factory)
    def for_attempt(token):
        recorder = fixture_call_recorder(factory,attempt_token=token) if record_call is None else record_call
        return lambda title,markdown: enrich(title,markdown,vocabulary_provider=provider,record_call=recorder)
    def run(title, markdown):
        raise RuntimeError('Existing enrichment requires a claimed attempt')
    run.for_attempt = for_attempt
    return run


def enrich_document(factory, document_id, *, enrich, worker_id='fixture-worker'):
    """Claim and commit before calling the supplied function, then save atomically."""
    validate_enricher(enrich)
    external = callable(getattr(enrich,'for_attempt',None))
    with factory() as conn:
        _guard(conn)
        claim=claim_enrichment(conn,document_id=document_id,worker_id=worker_id)
        if claim is None:
            return False
        row=conn.execute('SELECT title,markdown FROM ingest_documents WHERE id=%s',(document_id,)).fetchone()
        if row is None:
            raise ValueError('Claimed document missing')
        conn.execute("INSERT INTO ingest_enrichment_attempts(token,document_id,revision,worker_id,external,state) VALUES (%s,%s,%s,%s,%s,'started')",
                     (claim['token'],document_id,claim['revision'],worker_id,external))
    try:
        callback=enrich.for_attempt(claim['token']) if external else enrich
        result=callback(row[0] or '',row[1] or '')
        if not isinstance(result,dict) or not isinstance(result.get('model'),str) or not result['model']:
            raise ValueError('Enrichment result requires a model')
        with factory() as conn:
            applied=finish_with_graph(conn,document_id,revision=claim['revision'],token=claim['token'],
                                      summary=result.get('summary'),model=result['model'],result=result)
            conn.execute("UPDATE ingest_enrichment_attempts SET state=%s,finished_at=clock_timestamp() WHERE token=%s AND state='started'",
                         ('completed' if applied else 'stale',claim['token']))
            return applied
    except BaseException as exc:
        with factory() as conn:
            from pipeline.llm import CallRecordingError
            unknown = external or isinstance(exc, CallRecordingError)
            if unknown:
                conn.execute("UPDATE ingest_enrichment_jobs SET status='unknown',token=NULL,worker_id=NULL,started_at=NULL "
                             "WHERE document_id=%s AND revision=%s AND status='running' AND token=%s",
                             (document_id,claim['revision'],claim['token']))
            else:
                fail_enrichment(conn,document_id=document_id,**claim)
            conn.execute("UPDATE ingest_enrichment_attempts SET state=%s,finished_at=clock_timestamp() WHERE token=%s AND state='started'",
                         ('unknown' if unknown else 'failed',claim['token']))
        raise

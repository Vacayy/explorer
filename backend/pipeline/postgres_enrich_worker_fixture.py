"""Explicit enrichment callback for disposable fixtures; no model is invoked here."""
from pipeline.postgres_graph_fixture import _guard, finish_with_graph
from pipeline.postgres_ingest_fixture import claim_enrichment, fail_enrichment
from functools import partial
import math
from psycopg.types.json import Jsonb


def fixture_call_recorder(factory):
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
            conn.execute('INSERT INTO ingest_llm_calls(task,model,engine,effort,duration_ms,ok,usage,cost_usd) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                         (task,model,engine,effort,duration_ms,error is None,Jsonb(safe_usage),cost))
    return record


def validate_enricher(callback):
    """Reject passing the legacy function without an explicit provider."""
    from pipeline.enrich import enrich
    if callback is enrich:
        raise ValueError('Existing enrichment requires an explicit vocabulary provider')
    if isinstance(callback, partial) and callback.func is enrich:
        if not callable((callback.keywords or {}).get('vocabulary_provider')):
            raise ValueError('Existing enrichment requires an explicit vocabulary provider')


def existing_enricher(factory, *, record_call=None):
    """Use the existing single-document enrichment with this fixture's graph."""
    from pipeline.enrich import enrich
    from pipeline.postgres_enrich_vocabulary_fixture import vocabulary_provider
    provider = vocabulary_provider(factory)
    recorder = fixture_call_recorder(factory) if record_call is None else record_call
    def run(title, markdown):
        return enrich(title, markdown, vocabulary_provider=provider, record_call=recorder)
    return run


def enrich_document(factory, document_id, *, enrich, worker_id='fixture-worker'):
    """Claim and commit before calling the supplied function, then save atomically."""
    validate_enricher(enrich)
    with factory() as conn:
        _guard(conn)
        claim=claim_enrichment(conn,document_id=document_id,worker_id=worker_id)
        if claim is None:
            return False
        row=conn.execute('SELECT title,markdown FROM ingest_documents WHERE id=%s',(document_id,)).fetchone()
        if row is None:
            raise ValueError('Claimed document missing')
    try:
        result=enrich(row[0] or '',row[1] or '')
        if not isinstance(result,dict) or not isinstance(result.get('model'),str) or not result['model']:
            raise ValueError('Enrichment result requires a model')
        with factory() as conn:
            return finish_with_graph(conn,document_id,revision=claim['revision'],token=claim['token'],
                                     summary=result.get('summary'),model=result['model'],result=result)
    except BaseException as exc:
        with factory() as conn:
            from pipeline.llm import CallRecordingError
            if isinstance(exc, CallRecordingError):
                conn.execute("UPDATE ingest_enrichment_jobs SET status='unknown',token=NULL,worker_id=NULL,started_at=NULL "
                             "WHERE document_id=%s AND revision=%s AND status='running' AND token=%s",
                             (document_id,claim['revision'],claim['token']))
            else:
                fail_enrichment(conn,document_id=document_id,**claim)
        raise

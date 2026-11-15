"""Disposable collection cycles and an explicit in-process periodic experiment."""
from pipeline.postgres_enrich_worker_fixture import enrich_document, validate_enricher
from pipeline.postgres_ingest_runner_fixture import run_source
from pipeline.postgres_graph_fixture import _guard
from uuid import uuid4

CYCLE_LOCK=0x4558504C4359434C
MAX_ATTEMPTS=3


def run_cycle(connector, factory, *, enrich, worker_id='fixture-worker', batch_size=100):
    validate_enricher(enrich)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError('batch_size must be between 1 and 100')
    stats=run_source(connector,factory)
    source_type = getattr(connector, 'source_type', None)
    pending=[]
    remaining=0
    if source_type:
        with factory() as conn:
            _guard(conn)
            rows=conn.execute("SELECT j.document_id,count(*) OVER() FROM ingest_enrichment_jobs j "
                    "JOIN ingest_documents d ON d.id=j.document_id "
                    "WHERE j.auto_retry AND j.status IN ('pending','failed') AND j.attempt_count<%s AND d.source_type=%s "
                    "ORDER BY j.attempted_at ASC NULLS FIRST,j.document_id LIMIT %s", (MAX_ATTEMPTS,source_type,batch_size)).fetchall()
            pending=[row[0] for row in rows]
            remaining=(rows[0][1]-len(rows)) if rows else 0
    enriched=failed=0
    for ident in pending:
        try:
            if enrich_document(factory,ident,enrich=enrich,worker_id=worker_id):
                enriched+=1
        except Exception:
            failed+=1
    with factory() as conn:
        _guard(conn)
        counts=conn.execute("SELECT count(*) FILTER (WHERE j.status IN ('pending','failed') AND j.attempt_count<%s), "
                            "count(*) FILTER (WHERE j.status IN ('pending','failed') AND j.attempt_count>=%s), "
                            "count(*) FILTER (WHERE j.status='running') FROM ingest_enrichment_jobs j "
                            "JOIN ingest_documents d ON d.id=j.document_id WHERE j.auto_retry AND d.source_type=%s",
                            (MAX_ATTEMPTS,MAX_ATTEMPTS,source_type)).fetchone()
    return {**stats,'enriched':enriched,'enrichment_failed':failed,'enrichment_unselected_at_start':remaining,
            'enrichment_waiting':counts[0],'enrichment_held':counts[1],'enrichment_running':counts[2]}


def run_exclusive_cycle(connector, factory, *, enrich):
    """One process holds the lease; a later holder invalidates abandoned tokens."""
    with factory() as lease:
        _guard(lease)
        if not lease.execute('SELECT pg_try_advisory_lock(%s)',(CYCLE_LOCK,)).fetchone()[0]:
            raise RuntimeError('Another fixture cycle is running')
        try:
            with factory() as conn:
                _guard(conn)
                conn.execute("UPDATE ingest_enrichment_jobs SET status='failed',token=NULL,worker_id=NULL,started_at=NULL "
                             "WHERE status='running' AND worker_id LIKE 'cycle:%'")
            return run_cycle(connector,factory,enrich=enrich,worker_id='cycle:'+uuid4().hex)
        finally:
            lease.execute('SELECT pg_advisory_unlock(%s)',(CYCLE_LOCK,))


def run_periodic(connector_factory, factory, *, enrich, stop, interval_seconds, on_cycle, on_error):
    """Run serial cycles until stopped; caller supplies all side effects."""
    if interval_seconds <= 0:
        raise ValueError('interval_seconds must be positive')
    while not stop.is_set():
        try:
            result=run_exclusive_cycle(connector_factory(),factory,enrich=enrich)
        except Exception as exc:
            on_error(exc)
        else:
            on_cycle(result)
        if stop.wait(interval_seconds):
            return

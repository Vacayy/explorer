"""Disposable collection cycles and an explicit in-process periodic experiment."""
from pipeline.postgres_enrich_worker_fixture import enrich_document
from pipeline.postgres_ingest_runner_fixture import run_source
from pipeline.postgres_graph_fixture import _guard
from uuid import uuid4

CYCLE_LOCK=0x4558504C4359434C


def run_cycle(connector, factory, *, enrich, worker_id='fixture-worker'):
    changed=[]
    unchanged=[]
    def collect(result):
        if result['status'] in ('new','updated'):
            changed.append(result['id'])
        elif result['status'] == 'unchanged':
            unchanged.append(result['id'])
    stats=run_source(connector,factory,on_stored=collect)
    if unchanged:
        with factory() as conn:
            _guard(conn)
            retry={row[0] for row in conn.execute("SELECT document_id FROM ingest_enrichment_jobs "
                    "WHERE status='failed' AND document_id=ANY(%s)",(unchanged,))}
        changed.extend(ident for ident in unchanged if ident in retry)
    enriched=failed=0
    for ident in dict.fromkeys(changed):
        try:
            if enrich_document(factory,ident,enrich=enrich,worker_id=worker_id):
                enriched+=1
        except Exception:
            failed+=1
    return {**stats,'enriched':enriched,'enrichment_failed':failed}


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


def run_periodic(connector_factory, factory, *, enrich, stop, interval_seconds, on_cycle):
    """Run serial cycles until stopped; caller supplies all side effects."""
    if interval_seconds <= 0:
        raise ValueError('interval_seconds must be positive')
    while not stop.is_set():
        result=run_exclusive_cycle(connector_factory(),factory,enrich=enrich)
        on_cycle(result)
        if stop.wait(interval_seconds):
            return

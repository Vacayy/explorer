"""Explicit enrichment callback for disposable fixtures; no model is invoked here."""
from pipeline.postgres_graph_fixture import _guard, finish_with_graph
from pipeline.postgres_ingest_fixture import claim_enrichment, fail_enrichment


def enrich_document(factory, document_id, *, enrich, worker_id='fixture-worker'):
    """Claim and commit before calling the supplied function, then save atomically."""
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
    except BaseException:
        with factory() as conn:
            fail_enrichment(conn,document_id=document_id,**claim)
        raise

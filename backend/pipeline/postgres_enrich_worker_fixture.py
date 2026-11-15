"""Explicit enrichment callback for disposable fixtures; no model is invoked here."""
from pipeline.postgres_graph_fixture import _guard, finish_with_graph
from pipeline.postgres_ingest_fixture import claim_enrichment, fail_enrichment
from functools import partial


def validate_enricher(callback):
    """Reject passing the legacy function without an explicit provider."""
    from pipeline.enrich import enrich
    if callback is enrich:
        raise ValueError('Existing enrichment requires an explicit vocabulary provider')
    if isinstance(callback, partial) and callback.func is enrich:
        if not callable((callback.keywords or {}).get('vocabulary_provider')):
            raise ValueError('Existing enrichment requires an explicit vocabulary provider')


def existing_enricher(factory):
    """Use the existing single-document enrichment with this fixture's graph."""
    from pipeline.enrich import enrich
    from pipeline.postgres_enrich_vocabulary_fixture import vocabulary_provider
    provider = vocabulary_provider(factory)
    def run(title, markdown):
        return enrich(title, markdown, vocabulary_provider=provider)
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
    except BaseException:
        with factory() as conn:
            fail_enrichment(conn,document_id=document_id,**claim)
        raise

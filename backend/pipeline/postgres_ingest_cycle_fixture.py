"""One explicit, disposable collection/enrichment cycle; not a scheduler."""
from pipeline.postgres_enrich_worker_fixture import enrich_document
from pipeline.postgres_ingest_runner_fixture import run_source
from pipeline.postgres_graph_fixture import _guard


def run_cycle(connector, factory, *, enrich):
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
            if enrich_document(factory,ident,enrich=enrich):
                enriched+=1
        except Exception:
            failed+=1
    return {**stats,'enriched':enriched,'enrichment_failed':failed}

"""One explicit, disposable collection/enrichment cycle; not a scheduler."""
from pipeline.postgres_enrich_worker_fixture import enrich_document
from pipeline.postgres_ingest_runner_fixture import run_source


def run_cycle(connector, factory, *, enrich):
    changed=[]
    def collect(result):
        if result['status'] in ('new','updated'):
            changed.append(result['id'])
    stats=run_source(connector,factory,on_stored=collect)
    enriched=failed=0
    for ident in dict.fromkeys(changed):
        try:
            if enrich_document(factory,ident,enrich=enrich):
                enriched+=1
        except Exception:
            failed+=1
    return {**stats,'enriched':enriched,'enrichment_failed':failed}

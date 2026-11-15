"""Run existing connector/embedding code only against disposable PG fixtures.

The caller must isolate the process from external networks. No LLM is invoked.
The embedding cache must already exist; this module never downloads a model.
"""
import os
import re
from datetime import datetime, timezone
from pipeline import runner, search
from pipeline.postgres_ingest_fixture import store_raw_doc, store_embedding


def _guard(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')


def run_source(connector, factory, *, clock=lambda: datetime.now(timezone.utc)):
    with factory() as conn:
        _guard(conn)
    if getattr(connector,'after_store',None):
        raise ValueError('Connector side-effect hooks are not supported')
    def store(doc):
        observed=clock()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError('A timezone-aware collection time is required')
        with factory() as conn:
            _guard(conn)
            return store_raw_doc(conn,doc,fetched_at=observed.astimezone(timezone.utc).isoformat())
    return runner.run_source(connector,store=store)


def embed_document(factory, document_id):
    with factory() as conn:
        _guard(conn)
        row=conn.execute('SELECT title,markdown,revision FROM ingest_documents WHERE id=%s',(document_id,)).fetchone()
    if row is None:
        return False
    title,markdown,revision=row
    # Matches build_index's title + first 2000 characters, with local files only.
    vector=search._serialize(next(iter(search._get_model(local_files_only=True).embed([f'{title}\n{(markdown or "")[:2000]}']))))
    with factory() as conn:
        _guard(conn)
        return store_embedding(conn,document_id=document_id,revision=revision,embedding=vector,model=search.EMBED_MODEL)

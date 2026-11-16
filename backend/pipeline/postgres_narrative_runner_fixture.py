"""Explicit, disposable narrative execution; never schedules itself.

The caller must provide a private staging schema, a fixture embedder and an
explicit generator. This is not a production writer or concurrency protocol.
"""
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_narrative_ledger_fixture import claim_narrative, commit_staged_narrative
from pipeline.postgres_narrative_persist_fixture import prepare_fixture_narrative, persist_fixture_narrative


def run_fixture_narrative(factory, stage_factory, stage_schema, topic, *, embedder, generate, force=False):
    """Claim, prepare, generate outside transactions, then stage and commit."""
    if not callable(embedder) or not callable(generate):
        raise ValueError('Explicit embedder and generator required')
    with factory() as conn:
        _guard(conn)
        token=claim_narrative(conn,topic)
    if token is None:
        return {'status':'busy'}
    started=False
    try:
        with stage_factory() as stage:
            stage.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            if stage.execute('SELECT current_schema()').fetchone()[0] != stage_schema:
                raise ValueError('Staging schema does not match connection')
            prepared=prepare_fixture_narrative(stage,topic,embedder=embedder,force=force)
        if prepared['status'] != 'ready':
            with factory() as conn:
                conn.execute("UPDATE ingest_narrative_claims SET status='stale' WHERE topic=%s AND token=%s AND status='claimed'",(topic,token))
            return {'status':prepared['status']}
        started=True
        result=generate(prepared['prompt'])
        with stage_factory() as stage:
            stage.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            staged=persist_fixture_narrative(stage,topic,result,force=force)
            if staged['status'] != 'fresh':
                raise ValueError('Narrative staging did not produce a new version')
        with factory() as conn:
            applied=commit_staged_narrative(conn,topic,token,stage_schema)
        return {'status':'completed' if applied else 'stale'}
    except BaseException:
        with factory() as conn:
            _guard(conn)
            conn.execute("UPDATE ingest_narrative_claims SET status=%s WHERE topic=%s AND token=%s AND status='claimed'",
                         ('unknown' if started else 'stale',topic,token))
        raise

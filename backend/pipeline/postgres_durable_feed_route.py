"""Select a retained fixture feed generation for one request, never writes."""
import re
from uuid import UUID
from pipeline.postgres_graph_fixture import _guard

_SCHEMA=re.compile(r'^refactor_fixture_[0-9a-f]{32}$')


class FeedGenerationUnavailable(ValueError):
    pass


def select_feed_schema(source_factory, target_factory, source_schema, generation=None, fallback_schema=None):
    if not _SCHEMA.fullmatch(source_schema or ''):
        raise ValueError('Disposable source schema required')
    if generation is not None:
        generation=UUID(str(generation))
    with source_factory() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        _guard(conn)
        if conn.execute('SELECT current_schema()').fetchone()[0] != source_schema:
            raise ValueError('Source schema mismatch')
        if generation is None:
            row=conn.execute('''SELECT p.active_schema,p.generation FROM fixture_publication_state p
                JOIN fixture_publication_stages s ON s.schema_name=p.active_schema
                    AND s.generation=p.generation AND s.state='active'
                WHERE p.singleton''').fetchone()
        else:
            row=conn.execute("SELECT schema_name,generation FROM fixture_publication_stages "
                             "WHERE generation=%s AND state IN ('active','retained')",(generation,)).fetchone()
    if row is None and generation is not None and fallback_schema is not None:
        if not _SCHEMA.fullmatch(fallback_schema) or fallback_schema==source_schema:
            raise ValueError('Invalid fallback fixture schema')
        with target_factory(fallback_schema) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(conn)
            if conn.execute('SELECT current_schema()').fetchone()[0] != fallback_schema:
                raise ValueError('Fallback schema mismatch')
            prior=conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
            if prior is not None and prior[0]==generation:
                row=(fallback_schema,generation)
    if row is None:
        raise FeedGenerationUnavailable('Feed generation unavailable')
    schema,selected=row
    if not _SCHEMA.fullmatch(schema or '') or schema==source_schema:
        raise ValueError('Invalid published fixture schema')
    with target_factory(schema) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        _guard(conn)
        if conn.execute('SELECT current_schema()').fetchone()[0] != schema:
            raise ValueError('Target schema mismatch')
        actual=conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
        if actual is None or actual[0]!=selected:
            raise FeedGenerationUnavailable('Feed generation mismatch')
    return schema,selected

"""Copy an immutable document projection into a separate disposable PG schema.

This is a staging copy, not a new generation, activation, or ledger overlay.
The caller owns a repeatable-read transaction and the target must be empty.
"""
import os
import re
import uuid
from psycopg import sql

PROJECTION_TABLES = frozenset({
    'document_projection','document_list_projection','snapshot_metadata','legacy_snapshot_tables',
    'legacy_snapshot_rows','document_filter_order','document_entity_order','timeline_source_projection',
    'timeline_system_projection','timeline_source_metadata','archived_timeline_generations',
    'archived_timeline_source','archived_timeline_system','archived_timeline_legacy',
    'archived_document_details','media_generations','media_blobs','media_generation_refs',
    'document_embedding_metadata','document_embeddings','embedding_profile_attestations',
    'document_centroid_metadata','document_centroids',
})


def copy_projection(conn, source_schema, target_schema):
    valid = lambda name: bool(re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', name or ''))
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or not valid(source_schema) or
            not valid(target_schema) or source_schema == target_schema or
            conn.execute('SELECT current_database()').fetchone()[0] != 'fixture'):
        raise ValueError('Separate disposable fixture schemas required')
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read':
        raise ValueError('Repeatable-read transaction required')
    def tables(schema):
        return {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,))}
    destination = tables(target_schema)
    if destination != PROJECTION_TABLES or not destination.issubset(tables(source_schema)):
        raise ValueError('Projection schemas do not match')
    for table in destination:
        if conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {}.{})').format(
                sql.Identifier(target_schema), sql.Identifier(table))).fetchone()[0]:
            raise ValueError('Target projection must be empty')
    dependencies = {table: set() for table in destination}
    rows = conn.execute("SELECT child.relname,parent.relname FROM pg_constraint c "
                        "JOIN pg_class child ON child.oid=c.conrelid "
                        "JOIN pg_namespace ns ON ns.oid=child.relnamespace "
                        "JOIN pg_class parent ON parent.oid=c.confrelid "
                        "JOIN pg_namespace ps ON ps.oid=parent.relnamespace "
                        "WHERE c.contype='f' AND ns.nspname=%s AND ps.nspname=%s", (target_schema,target_schema))
    for child,parent in rows:
        if child != parent:
            dependencies[child].add(parent)
    done = set()
    while len(done) < len(destination):
        ready = sorted(table for table in destination-done if dependencies[table] <= done)
        if not ready:
            raise ValueError('Unsupported cyclic projection dependencies')
        for table in ready:
            conn.execute(sql.SQL('INSERT INTO {}.{} SELECT * FROM {}.{}').format(
                sql.Identifier(target_schema),sql.Identifier(table),sql.Identifier(source_schema),sql.Identifier(table)))
            done.add(table)
    snapshot = conn.execute(sql.SQL('SELECT generation_id FROM {}.snapshot_metadata WHERE singleton').format(
        sql.Identifier(target_schema))).fetchone()
    if snapshot is None:
        raise ValueError('Source projection has no active generation')
    old, new = snapshot[0], uuid.uuid4()
    for table in ('document_embedding_metadata','document_centroid_metadata'):
        mismatch = conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {}.{} WHERE generation_id<>%s)').format(
            sql.Identifier(target_schema),sql.Identifier(table)), (old,)).fetchone()[0]
        if mismatch:
            raise ValueError('Projection metadata generation mismatch')
        conn.execute(sql.SQL('UPDATE {}.{} SET generation_id=%s WHERE generation_id=%s').format(
            sql.Identifier(target_schema),sql.Identifier(table)), (new,old))
    conn.execute(sql.SQL('UPDATE {}.embedding_profile_attestations SET generation_id=%s WHERE generation_id=%s').format(
        sql.Identifier(target_schema)), (new,old))
    media = conn.execute(sql.SQL('SELECT 1 FROM {}.media_generations WHERE generation_id=%s').format(
        sql.Identifier(target_schema)), (old,)).fetchone()
    if media:
        conn.execute(sql.SQL('INSERT INTO {}.media_generations VALUES (%s)').format(sql.Identifier(target_schema)), (new,))
        conn.execute(sql.SQL('INSERT INTO {}.media_generation_refs '
                             'SELECT %s,path,digest FROM {}.media_generation_refs WHERE generation_id=%s').format(
            sql.Identifier(target_schema),sql.Identifier(target_schema)), (new,old))
    conn.execute(sql.SQL('UPDATE {}.snapshot_metadata SET generation_id=%s WHERE singleton').format(
        sql.Identifier(target_schema)), (new,))
    return {'tables': len(done), 'generation': new}

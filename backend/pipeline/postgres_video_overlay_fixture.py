"""Disposable copy-on-write video rows for an isolated graph-overlay fork.

The base snapshot remains intact. This only establishes a shared read path;
it does not schedule or run a model, nor rebuild document/search projections.
"""
import re
from psycopg import sql
from pipeline.postgres_graph_fixture import _guard


def install_video_overlay(target, base_schema):
    _guard(target)
    current = target.execute('SELECT current_schema()').fetchone()[0]
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', base_schema or '') or base_schema == current:
        raise ValueError('Separate fixture base required')
    with target.transaction():
        if target.execute("SELECT to_regclass('question_graph_overlay_rows')").fetchone()[0] is None:
            raise ValueError('Graph overlay must already exist')
        if target.execute("SELECT to_regclass('video_digest_overlay_rows')").fetchone()[0] is not None:
            raise ValueError('Video overlay already exists')
        depends = target.execute("""SELECT EXISTS(SELECT 1 FROM pg_rewrite rw
            JOIN pg_depend dep ON dep.classid='pg_rewrite'::regclass AND dep.objid=rw.oid
            JOIN pg_class source ON source.oid=dep.refobjid JOIN pg_namespace ns ON ns.oid=source.relnamespace
            WHERE rw.ev_class=to_regclass('legacy_snapshot_rows') AND ns.nspname=%s AND source.relname='legacy_snapshot_rows')""", (base_schema,)).fetchone()[0]
        if not depends:
            raise ValueError('Fork does not reference the specified base')
        target.execute("CREATE TABLE video_digest_overlay_rows (table_name TEXT NOT NULL, row_ordinal BIGINT NOT NULL, "
                       "row_data JSONB NOT NULL, PRIMARY KEY(table_name,row_ordinal), "
                       "CHECK(table_name IN ('raw_documents','youtube_digest_jobs')))")
        target.execute("CREATE UNIQUE INDEX video_override_document ON video_digest_overlay_rows ((row_data->>'id')) "
                       "WHERE table_name='raw_documents'")
        target.execute("CREATE UNIQUE INDEX video_override_job ON video_digest_overlay_rows ((row_data->>'doc_id')) "
                       "WHERE table_name='youtube_digest_jobs'")
        target.execute(sql.SQL("""CREATE OR REPLACE VIEW legacy_snapshot_rows AS
            SELECT b.* FROM {}.legacy_snapshot_rows b
            WHERE b.table_name NOT IN ('entity_relations','narrative_edge_evidence')
              AND (b.table_name NOT IN ('raw_documents','youtube_digest_jobs') OR NOT EXISTS
                (SELECT 1 FROM video_digest_overlay_rows v WHERE v.table_name=b.table_name AND v.row_ordinal=b.row_ordinal))
            UNION ALL SELECT * FROM question_graph_overlay_rows
            UNION ALL SELECT * FROM video_digest_overlay_rows""").format(sql.Identifier(base_schema)))
    return {'initialized': True}

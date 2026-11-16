"""Small, writable graph overlay for an otherwise read-only fixture fork.

Only narrative edge confirmation is supported. Other graph writers must not
assume this overlay is a complete ingest graph ledger.
"""
import re
from psycopg import sql
from pipeline.postgres_graph_fixture import _guard


def install_graph_overlay(target, base_schema):
    _guard(target)
    current=target.execute('SELECT current_schema()').fetchone()[0]
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',base_schema or '') or base_schema==current:
        raise ValueError('Separate fixture base required')
    with target.transaction():
        kind=target.execute("SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname='legacy_snapshot_rows'").fetchone()
        if not kind or kind[0]!='v':raise ValueError('A read-only fork is required')
        # Do not replace a fork that points at a different base.
        depends=target.execute("""SELECT EXISTS(SELECT 1 FROM pg_rewrite rw
            JOIN pg_depend dep ON dep.classid='pg_rewrite'::regclass AND dep.objid=rw.oid
            JOIN pg_class source ON source.oid=dep.refobjid JOIN pg_namespace ns ON ns.oid=source.relnamespace
            WHERE rw.ev_class=to_regclass('legacy_snapshot_rows') AND ns.nspname=%s AND source.relname='legacy_snapshot_rows')""",(base_schema,)).fetchone()[0]
        if not depends:raise ValueError('Fork does not reference the specified base')
        base=sql.Identifier(base_schema)
        for table in ('entity_relations','narrative_edge_evidence'):
            source=target.execute(sql.SQL('SELECT row_count FROM {}.legacy_snapshot_tables WHERE table_name=%s').format(base),(table,)).fetchone()
            count=target.execute(sql.SQL('SELECT count(*) FROM {}.legacy_snapshot_rows WHERE table_name=%s').format(base),(table,)).fetchone()[0]
            if not source or source[0]!=count:raise ValueError('Complete base graph snapshot required')
        target.execute('''CREATE TABLE question_graph_overlay_rows (
            table_name TEXT NOT NULL,row_ordinal BIGINT NOT NULL,row_data JSONB NOT NULL,
            PRIMARY KEY(table_name,row_ordinal),CHECK(table_name IN ('entity_relations','narrative_edge_evidence')))''')
        target.execute(sql.SQL("INSERT INTO question_graph_overlay_rows SELECT * FROM {}.legacy_snapshot_rows WHERE table_name IN ('entity_relations','narrative_edge_evidence')").format(base))
        target.execute('DROP VIEW legacy_snapshot_rows')
        target.execute(sql.SQL("""CREATE VIEW legacy_snapshot_rows AS
            SELECT * FROM {}.legacy_snapshot_rows WHERE table_name NOT IN ('entity_relations','narrative_edge_evidence')
            UNION ALL SELECT * FROM question_graph_overlay_rows""").format(base))
        target.execute('CREATE TABLE question_graph_overlay_state(singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton))')
        target.execute('CREATE TABLE question_graph_overlay_relations(id BIGINT PRIMARY KEY,source_row JSONB NOT NULL)')
        target.execute('CREATE TABLE question_graph_overlay_evidence(id BIGINT PRIMARY KEY,source_row JSONB NOT NULL)')
        target.execute("""INSERT INTO question_graph_overlay_relations SELECT (row_data->>'id')::bigint,row_data
            FROM question_graph_overlay_rows WHERE table_name='entity_relations'""")
        target.execute("""INSERT INTO question_graph_overlay_evidence SELECT (row_data->>'id')::bigint,row_data
            FROM question_graph_overlay_rows WHERE table_name='narrative_edge_evidence'""")
        target.execute('INSERT INTO question_graph_overlay_state DEFAULT VALUES')
        return {'relations':target.execute('SELECT count(*) FROM question_graph_overlay_relations').fetchone()[0],
                'evidence':target.execute('SELECT count(*) FROM question_graph_overlay_evidence').fetchone()[0]}

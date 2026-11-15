"""Disposable read adapter for the existing transcript document graph."""
import os
import re


def document_graph(conn, document_id):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A read-only repeatable-read transaction is required')
    nodes = conn.execute("""
        SELECT DISTINCT (e.row_data->>'id')::bigint id,e.row_data->>'name' name,
               e.row_data->>'type' type,l.row_data->>'link_type' link_type,
               (l.row_data->>'confidence')::double precision confidence
        FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e
          ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id'
        WHERE l.table_name='entity_links' AND l.row_data->>'doc_id'=%s
        ORDER BY confidence DESC NULLS LAST,name LIMIT 30
    """, (str(document_id),)).fetchall()
    # SQLite DISTINCT ignores confidence, even though the ordering uses it.
    # Reject ambiguous input until the SQLite plan's tie behavior is reproduced.
    if len({tuple(row[:4]) for row in nodes}) != len(nodes):
        raise ValueError('Ambiguous duplicate document links')
    edges = conn.execute("""
        SELECT r.row_data->>'rel_type',r.row_data->>'effect_direction',
               (s.row_data->>'id')::bigint,s.row_data->>'name',s.row_data->>'type',
               (d.row_data->>'id')::bigint,d.row_data->>'name',d.row_data->>'type'
        FROM legacy_snapshot_rows r
        JOIN legacy_snapshot_rows s ON s.table_name='entities' AND s.row_data->>'id'=r.row_data->>'src_id'
        JOIN legacy_snapshot_rows d ON d.table_name='entities' AND d.row_data->>'id'=r.row_data->>'dst_id'
        WHERE r.table_name='entity_relations' AND r.row_data->>'source_doc_id'=%s
          AND r.row_data->>'rel_type' IN ('CAUSES','BENEFITS_FROM')
        ORDER BY (r.row_data->>'id')::bigint
    """, (str(document_id),)).fetchall()
    return {'nodes':[dict(zip(('id','name','type','link_type'),row[:4])) for row in nodes],
            'edges':[dict(zip(('rel_type','effect_direction','from_id','from','from_type','to_id','to','to_type'),row)) for row in edges]}

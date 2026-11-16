"""Publish what a legacy graph-writing computation changed (narrative generation), single-path candidate.

The unchanged legacy function runs on a projection connection with writable TEMP copies of the graph
tables (`LegacyProjection.write_connection(extra=GRAPH)`). Its graph diff, by id, goes where collected
graph changes go: new entities as overlay rows, changed entities and keywords as row revisions, relations
and edge evidence into the candidate's graph ledger. A row the candidate changed meanwhile is kept in
`collected_change_conflicts` (target table) for the field-wise merge, never overwritten.
"""
from psycopg.types.json import Jsonb

from pipeline.postgres_collected_changes_fixture import _apply_graph, _pg_graph_row
from pipeline.postgres_graph_fixture import GRAPH_LOCK

GRAPH = ('entities', 'entity_relations', 'narrative_edge_evidence')


def snapshot(conn):
    """{table: {id: row}} of the request's TEMP graph copies."""
    return {table: {row['id']: dict(row) for row in conn.execute(f'SELECT * FROM temp."{table}"')} for table in GRAPH}


def publish(pg, before, after, *, run_id):
    """Apply one computation's graph diff in the caller's transaction; returns counts."""
    from pipeline.postgres_owner_overrides import record_outputs
    pg.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
    added = changed = kept = 0
    produced = []
    for table in GRAPH:
        old, new = before[table], after[table]
        for ident in sorted(set(new) - set(old)):
            if _pg_graph_row(pg, table, ident)[1] is not None:
                raise RuntimeError(f'{table} id {ident} was taken meanwhile; nothing published')
            if table == 'entities':
                pg.execute("INSERT INTO video_digest_overlay_rows VALUES ('entities',%s,%s)", (-ident, Jsonb(new[ident])))
            else:
                _apply_graph(pg, table, ident, None, new[ident])
            added += 1
            produced.append((table, ident))
        for ident in sorted(i for i in set(old) & set(new) if old[i] != new[i]) + sorted(set(old) - set(new)):
            ordinal, current = _pg_graph_row(pg, table, ident)
            if current != old[ident]:
                pg.execute('INSERT INTO collected_change_conflicts(run_id,document_id,target_table,before_state,collected_state,'
                           "candidate_state,status,reason) VALUES (%s,%s,%s,%s,%s,%s,'pending','changed in the candidate meanwhile')",
                           (run_id, ident, table, Jsonb(old[ident]), Jsonb(new.get(ident)), Jsonb(current)))
                kept += 1
                continue
            _apply_graph(pg, table, ident, ordinal, new.get(ident))
            changed += 1
            produced.append((table, ident))
    record_outputs(pg, run_id, produced)
    return {'added': added, 'changed': changed, 'kept': kept}

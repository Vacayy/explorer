"""Move the candidate's legacy ids out of the MacBook's range (architect #3 6943703383, PM 6943627803·6943708476).

Rows the candidate collected before its id band (refactor_collect_trial.ID_BANDS) took the ids the MacBook issues next,
so the cutover publication would meet them. This renumbers them to band + old id in one transaction, through every
internal reference whose meaning is known (a document, entity or relation id: columns and JSON keys listed below,
found by the catalogue scan of #3 6943842713). Above the base snapshot's maximum only candidate rows exist, so a
value there in such a column is unambiguous. Old ids in external URLs are never reinterpreted (they open the MacBook's
document after the cutover). The map (candidate_id_remap) makes a second run change nothing and `rollback` the exact
inverse.
"""
from pipeline.postgres_graph_fixture import _guard

KINDS = {'document': ('raw_documents', 100_000_000), 'entity': ('entities', 100_000_000),
         'relation': ('entity_relations', 100_000_000), 'keyword': ('entity_keywords', 100_000_000),
         'evidence': ('narrative_edge_evidence', 10_000_000_000)}
# (table, column, kind): plain columns holding one id.
COLUMNS = (*((table, 'document_id', 'document') for table in (
               'collected_publications', 'collected_document_list_projection', 'collected_document_entity_order',
               'collected_included_documents', 'collected_timeline_source_metadata', 'collected_timeline_source_projection',
               'collected_change_conflicts', 'revised_document_entity_order', 'revised_timeline_source_metadata',
               'revised_timeline_source_projection', 'document_embedding_overrides', 'video_projection_overrides',
               'video_digest_work', 'video_model_calls', 'conversation_import_unresolved_docs', 'study_sessions')),
           ('collected_document_projection', 'id', 'document'),
           ('computed_doc_claims', 'doc_id', 'document'),
           ('questions', 'source_doc_id', 'document'),
           ('question_graph_overlay_relations', 'id', 'relation'),
           *((table, 'entity_id', 'entity') for table in (
               'collected_document_entity_order', 'revised_document_entity_order', 'owner_follows', 'chat_entity_links',
               'observations')),
           ('conversations', 'anchor_entity_id', 'entity'))
# (table, jsonb column, key, kind, filter on the row's table_name or None): ids inside JSON rows.
JSON_KEYS = (('collected_document_projection', 'detail_document', 'id', 'document', None),
             ('collected_document_list_projection', 'list_document', 'id', 'document', None),
             ('collected_timeline_source_projection', 'document', 'id', 'document', None),
             ('video_digest_overlay_rows', 'row_data', 'id', 'document', 'raw_documents'),
             ('video_digest_overlay_rows', 'row_data', 'doc_id', 'document', 'enrichments'),
             ('video_digest_overlay_rows', 'row_data', 'doc_id', 'document', 'entity_links'),
             ('video_digest_overlay_rows', 'row_data', 'entity_id', 'entity', 'entity_links'),
             ('video_digest_overlay_rows', 'row_data', 'id', 'entity', 'entities'),
             ('video_digest_overlay_rows', 'row_data', 'id', 'keyword', 'entity_keywords'),
             ('video_digest_overlay_rows', 'row_data', 'entity_id', 'entity', 'entity_keywords'),
             ('question_graph_overlay_rows', 'row_data', 'id', 'relation', 'entity_relations'),
             ('question_graph_overlay_rows', 'row_data', 'src_id', 'entity', 'entity_relations'),
             ('question_graph_overlay_rows', 'row_data', 'dst_id', 'entity', 'entity_relations'),
             ('question_graph_overlay_rows', 'row_data', 'source_doc_id', 'document', 'entity_relations'),
             ('question_graph_overlay_rows', 'row_data', 'id', 'evidence', 'narrative_edge_evidence'),
             ('question_graph_overlay_rows', 'row_data', 'entity_relation_id', 'relation', 'narrative_edge_evidence'),
             ('question_graph_overlay_rows', 'row_data', 'doc_id', 'document', 'narrative_edge_evidence'),
             ('question_graph_overlay_relations', 'source_row', 'id', 'relation', None),
             ('question_graph_overlay_relations', 'source_row', 'src_id', 'entity', None),
             ('question_graph_overlay_relations', 'source_row', 'dst_id', 'entity', None),
             ('question_graph_overlay_relations', 'source_row', 'source_doc_id', 'document', None),
             ('question_graph_overlay_evidence', 'source_row', 'id', 'evidence', None),
             ('question_graph_overlay_evidence', 'source_row', 'entity_relation_id', 'relation', None),
             ('question_graph_overlay_evidence', 'source_row', 'doc_id', 'document', None),
             # Supplement rows a candidate job wrote about its documents (replaced by the MacBook's at the cutover).
             *(('legacy_supplement_rows', 'row_data', 'doc_id', 'document', table) for table in
               ('knowledge_doc_scans', 'image_backfill_docs', 'knowledge_evidence', 'exp_feed_docs', 'scrap_links')))
# (table, array column, kind): id lists.
ARRAYS = (('collected_publications', 'entity_ids', 'entity'), ('collected_publications', 'keyword_ids', 'keyword'),
          ('collected_publications', 'relation_ids', 'relation'))
# Overlay rows keyed by the negated id (raw_documents, entities, entity_keywords: -id).
ORDINALS = (('video_digest_overlay_rows', 'raw_documents', 'document'), ('video_digest_overlay_rows', 'entities', 'entity'),
            ('video_digest_overlay_rows', 'entity_keywords', 'keyword'))
# candidate_outputs.row_key by its table.
OUTPUTS = {'raw_documents': 'document', 'entities': 'entity', 'entity_relations': 'relation', 'entity_keywords': 'keyword',
           'narrative_edge_evidence': 'evidence'}


def _exists(conn, table, column=None):
    if column is None:
        return conn.execute('SELECT to_regclass(%s) IS NOT NULL', (table,)).fetchone()[0]
    return conn.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s '
                        'AND column_name=%s', (table, column)).fetchone() is not None


def plan(conn, base_schema):
    """(kind, old, new) of every candidate row between the base snapshot's maximum and its band."""
    rows = []
    for kind, (table, band) in KINDS.items():
        top = conn.execute(f"SELECT COALESCE(max((row_data->>'id')::bigint),0) FROM {base_schema}.legacy_snapshot_rows "
                           'WHERE table_name=%s', (table,)).fetchone()[0]
        rows += [(kind, old, band + old) for (old,) in conn.execute(
            "SELECT DISTINCT (row_data->>'id')::bigint FROM legacy_snapshot_rows WHERE table_name=%s "
            "AND (row_data->>'id')::bigint > %s AND (row_data->>'id')::bigint < %s ORDER BY 1", (table, top, band))]
    return rows


def _apply(conn, pairs):
    """Rewrite every listed reference from old to new for `pairs` [(kind, old, new)]; returns updated counts."""
    conn.execute('CREATE TEMP TABLE IF NOT EXISTS remap_pairs (kind TEXT, old BIGINT, new BIGINT) ON COMMIT DROP')
    conn.execute('DELETE FROM remap_pairs')
    with conn.cursor().copy('COPY remap_pairs FROM STDIN') as copy:
        for pair in pairs:
            copy.write_row(pair)
    counts = {}
    for table, column, kind in COLUMNS:
        if _exists(conn, table, column):
            counts[f'{table}.{column}'] = conn.execute(
                f'UPDATE "{table}" t SET "{column}" = m.new FROM remap_pairs m WHERE m.kind=%s AND t."{column}" = m.old',
                (kind,)).rowcount
    for table, column, key, kind, row_table in JSON_KEYS:
        if not _exists(conn, table, column):
            continue
        scope = ' AND t.table_name = %s' if row_table else ''
        counts[f'{table}.{column}.{key}' + (f'[{row_table}]' if row_table else '')] = conn.execute(
            f"""UPDATE "{table}" t SET "{column}" = jsonb_set(t."{column}", ARRAY[%s],
                    CASE WHEN jsonb_typeof(t."{column}"->%s) = 'string' THEN to_jsonb(m.new::text) ELSE to_jsonb(m.new) END)
                FROM remap_pairs m WHERE m.kind = %s AND jsonb_typeof(t."{column}") = 'object'
                AND t."{column}"->>%s = m.old::text{scope}""",
            (key, key, kind, key, *((row_table,) if row_table else ()))).rowcount
    for table, column, kind in ARRAYS:
        if _exists(conn, table, column):
            counts[f'{table}.{column}'] = conn.execute(
                f"""UPDATE "{table}" t SET "{column}" = (SELECT array_agg(COALESCE(m.new, u.x) ORDER BY u.o)
                        FROM unnest(t."{column}") WITH ORDINALITY u(x, o) LEFT JOIN remap_pairs m ON m.kind = %s AND m.old = u.x)
                    WHERE t."{column}" && (SELECT array_agg(old) FROM remap_pairs WHERE kind = %s)""", (kind, kind)).rowcount
    for table, row_table, kind in ORDINALS:
        counts[f'{table}.row_ordinal[{row_table}]'] = conn.execute(
            f'UPDATE "{table}" t SET row_ordinal = -m.new FROM remap_pairs m '
            'WHERE m.kind = %s AND t.table_name = %s AND t.row_ordinal = -m.old', (kind, row_table)).rowcount
    counts['owner_saved_items.ref[doc]'] = conn.execute(
        "UPDATE owner_saved_items t SET ref = m.new::text FROM remap_pairs m WHERE m.kind = 'document' "
        "AND t.kind = 'doc' AND t.ref = m.old::text").rowcount
    for table, kind in OUTPUTS.items():
        counts[f'candidate_outputs.row_key[{table}]'] = conn.execute(
            'UPDATE candidate_outputs t SET row_key = m.new::text FROM remap_pairs m '
            'WHERE m.kind = %s AND t.table_name = %s AND t.row_key = m.old::text', (kind, table)).rowcount
    return {name: n for name, n in counts.items() if n}


def apply(conn, base_schema):
    """Renumber what `plan` finds (pairs already in the map are not found again: a second run changes nothing)."""
    _guard(conn)
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS candidate_id_remap (kind TEXT NOT NULL, old_id BIGINT NOT NULL, '
                     'new_id BIGINT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), rolled_back_at TIMESTAMPTZ, '
                     'PRIMARY KEY (kind, old_id))')
        pairs = plan(conn, base_schema)
        if not pairs:
            return {'pairs': 0, 'updated': {}}
        counts = _apply(conn, pairs)
        for kind, old, new in pairs:
            conn.execute('INSERT INTO candidate_id_remap (kind, old_id, new_id) VALUES (%s,%s,%s) ON CONFLICT (kind, old_id) '
                         'DO UPDATE SET new_id = excluded.new_id, applied_at = now(), rolled_back_at = NULL', (kind, old, new))
    return {'pairs': len(pairs), 'updated': counts}


def rollback(conn):
    """The exact inverse of the applied map."""
    _guard(conn)
    with conn.transaction():
        pairs = [(kind, new, old) for kind, old, new in conn.execute(
            'SELECT kind, old_id, new_id FROM candidate_id_remap WHERE rolled_back_at IS NULL')]
        counts = _apply(conn, pairs) if pairs else {}
        conn.execute('UPDATE candidate_id_remap SET rolled_back_at = now() WHERE rolled_back_at IS NULL')
    return {'pairs': len(pairs), 'updated': counts}

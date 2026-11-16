"""Use the original verdict rules against a private PG question capture.

Question-associated graph confirmation requires an initialized, writable
shared graph ledger with matching source records. Not mounted to a user API.
"""
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard, GRAPH_LOCK
from pipeline.postgres_questions_fixture import _projection

INPUT_TABLES=('questions','sub_questions','proxy_registry','proxy_observations','entity_relations','narrative_edge_evidence')


def _inputs(connect):
    with connect() as pg:
        _guard(pg)
        return pg.execute('''SELECT table_name,row_ordinal,row_data FROM question_capture_rows
            WHERE table_name=ANY(%s) ORDER BY table_name,row_ordinal''',(list(INPUT_TABLES),)).fetchall()


def rollup_question(connect,question_id,*,run_llm):
    """Compute using original rules, reject stale inputs, commit atomically."""
    before=_inputs(connect)
    def summarize(db,q,lead,confirm,div):
        subs=db.execute('SELECT text,verdict FROM sub_questions WHERE question_id=?',(q['id'],)).fetchall()
        text=' / '.join(f"{s['text']}: {questions._KO.get(s['verdict'],'미판정')}" for s in subs)
        prompt=questions._SUMMARY_PROMPT.format(q=q['text'],lead=questions._KO.get(lead),confirm=questions._KO.get(confirm),subs=text)
        try:
            output=run_llm(prompt,task='question.summarize').text
            return output.strip().split('\n')[0][:400] or None
        except Exception:return None
    graph={'requested':False,'narrative_id':None,'edge_ids':[]}
    def graph_needed(db,qid,narrative_id):
        graph['requested']=True;graph['narrative_id']=narrative_id
        graph['edge_ids']=[r[0] for r in db.execute('SELECT DISTINCT entity_relation_id FROM narrative_edge_evidence WHERE narrative_id=?',(narrative_id,))]
        return questions._confirm_edges(db,qid,narrative_id)
    with _projection(connect,writable=True) as factory:
        if _inputs(connect)!=before:return {'status':'stale'}
        result=questions.rollup(question_id,connection_factory=factory,summarizer=summarize,confirm_edges=graph_needed)
        if 'error' in result:return result
        db=factory()
        try:
            question=dict(db.execute('SELECT * FROM questions WHERE id=?',(question_id,)).fetchone())
            subs=[dict(r) for r in db.execute('SELECT * FROM sub_questions WHERE question_id=?',(question_id,))]
            edges=[dict(r) for r in db.execute('SELECT * FROM entity_relations WHERE id IN ('+','.join('?' for _ in graph['edge_ids'])+')',graph['edge_ids'])] if graph['edge_ids'] else []
        finally:db.close()
    with connect() as pg:
        _guard(pg)
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
        current=pg.execute('''SELECT table_name,row_ordinal,row_data FROM question_capture_rows
            WHERE table_name=ANY(%s) ORDER BY table_name,row_ordinal''',(list(INPUT_TABLES),)).fetchall()
        if current!=before:return {'status':'stale'}
        if graph['requested']:
            overlay=pg.execute("SELECT to_regclass('question_graph_overlay_state')").fetchone()[0] is not None
            if overlay:
                rows_table='question_graph_overlay_rows';relations_table='question_graph_overlay_relations';evidence_table='question_graph_overlay_evidence'
                state_tables=('question_graph_overlay_state',)
            else:
                rows_table='legacy_snapshot_rows';relations_table='ingest_graph_relations';evidence_table='ingest_narrative_evidence'
                state_tables=('ingest_graph_state','ingest_narrative_ledger_state')
            required=(rows_table,relations_table,evidence_table,*state_tables)
            kinds=dict(pg.execute("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=ANY(%s)",(list(required),)).fetchall())
            if any(kinds.get(name) not in ('r','p') for name in required):
                raise NotImplementedError('Writable shared graph ledger is not connected')
            pg.execute('LOCK TABLE '+rows_table+' IN SHARE ROW EXCLUSIVE MODE')
            pg.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
            if any(not pg.execute('SELECT 1 FROM '+table).fetchone() for table in state_tables):
                raise NotImplementedError('Shared graph ledger is not initialized')
            narrative=str(graph['narrative_id'])
            captured=[r[2] for r in before if r[0]=='narrative_edge_evidence' and str(r[2].get('narrative_id'))==narrative]
            ledger=[r[0] for r in pg.execute("SELECT source_row FROM "+evidence_table+" WHERE source_row->>'narrative_id'=%s ORDER BY id",(narrative,))]
            legacy=[r[0] for r in pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='narrative_edge_evidence' AND row_data->>'narrative_id'=%s ORDER BY (row_data->>'id')::bigint",(narrative,))]
            order=lambda rows:sorted(rows,key=lambda r:r['id'])
            if order(captured)!=order(ledger) or order(captured)!=order(legacy):return {'status':'stale'}
            prior={r[2]['id']:r[2] for r in before if r[0]=='entity_relations'}
            if set(graph['edge_ids']) != {edge['id'] for edge in edges}:return {'status':'stale'}
            for edge in edges:
                original=prior.get(edge['id'])
                ledger_row=pg.execute('SELECT source_row FROM '+relations_table+' WHERE id=%s FOR UPDATE',(edge['id'],)).fetchone()
                legacy_rows=pg.execute("SELECT row_data FROM "+rows_table+" WHERE table_name='entity_relations' AND row_data->>'id'=%s FOR UPDATE",(str(edge['id']),)).fetchall()
                if not original or not ledger_row or ledger_row[0]!=original or len(legacy_rows)!=1 or legacy_rows[0][0]!=original:return {'status':'stale'}
            for edge in edges:
                pg.execute('UPDATE '+relations_table+' SET source_row=%s WHERE id=%s',(Jsonb(edge),edge['id']))
                pg.execute("UPDATE "+rows_table+" SET row_data=%s WHERE table_name='entity_relations' AND row_data->>'id'=%s",(Jsonb(edge),str(edge['id'])))
                pg.execute("UPDATE question_capture_rows SET row_data=%s WHERE table_name='entity_relations' AND row_data->>'id'=%s",(Jsonb(edge),str(edge['id'])))
        for table,rows in (('questions',[question]),('sub_questions',subs)):
            for row in rows:
                changed=pg.execute('UPDATE question_capture_rows SET row_data=%s WHERE table_name=%s AND row_data->>\'id\'=%s',
                                   (Jsonb(row),table,str(row['id'])))
                if changed.rowcount!=1:raise ValueError('Question capture identity mismatch')
    return {'status':'ok',**result}

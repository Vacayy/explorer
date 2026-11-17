"""Use the original verdict rules against a private PG question capture.

Question-associated graph confirmation requires an initialized, writable
shared graph ledger with matching source records. Not mounted to a user API.
"""
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard, GRAPH_LOCK
from pipeline.postgres_question_members import member_question
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


def rollup_question_native(connect, question_id, *, run_llm):
    """Apply existing verdict rules and graph confirmations to one PG fixture."""
    from psycopg.rows import dict_row

    def capture(pg):
        with pg.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT * FROM questions WHERE id=%s', (question_id,))
            question = cur.fetchone()
            cur.execute('SELECT * FROM sub_questions WHERE question_id=%s ORDER BY id', (question_id,))
            subs = cur.fetchall()
            cur.execute('SELECT p.* FROM proxy_registry p JOIN sub_questions s ON s.id=p.sub_question_id '
                        'WHERE s.question_id=%s AND p.active=1 ORDER BY p.id', (question_id,))
            proxies = cur.fetchall()
            cur.execute('SELECT o.* FROM proxy_observations o JOIN proxy_registry p ON p.id=o.proxy_id '
                        'JOIN sub_questions s ON s.id=p.sub_question_id WHERE s.question_id=%s AND p.active=1 '
                        'ORDER BY o.id', (question_id,))
            return question, subs, proxies, cur.fetchall()

    def capture_graph(pg, narrative_id):
        required = ('question_graph_overlay_state', 'question_graph_overlay_rows',
                    'question_graph_overlay_relations', 'question_graph_overlay_evidence')
        kinds = dict(pg.execute("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND c.relname=ANY(%s)", (list(required),)).fetchall())
        if any(kinds.get(name) not in ('r', 'p') for name in required) or not pg.execute('SELECT 1 FROM question_graph_overlay_state').fetchone():
            raise NotImplementedError('Writable shared graph ledger is not connected')
        evidence = pg.execute("SELECT source_row FROM question_graph_overlay_evidence WHERE source_row->>'narrative_id'=%s ORDER BY id", (str(narrative_id),)).fetchall()
        rows = pg.execute("SELECT row_data FROM question_graph_overlay_rows WHERE table_name='narrative_edge_evidence' AND row_data->>'narrative_id'=%s ORDER BY (row_data->>'id')::bigint", (str(narrative_id),)).fetchall()
        if evidence != rows:
            raise ValueError('Graph evidence representations disagree')
        edge_ids = sorted({int(row[0]['entity_relation_id']) for row in evidence if row[0].get('entity_relation_id') is not None})
        relations = pg.execute('SELECT id,source_row FROM question_graph_overlay_relations WHERE id=ANY(%s) ORDER BY id', (edge_ids,)).fetchall()
        projected = pg.execute("SELECT (row_data->>'id')::bigint,row_data FROM question_graph_overlay_rows "
            "WHERE table_name='entity_relations' AND (row_data->>'id')::bigint=ANY(%s) ORDER BY 1", (edge_ids,)).fetchall()
        if relations != projected or len(relations) != len(edge_ids):
            raise ValueError('Graph relation representations disagree')
        return evidence, relations

    with connect() as pg:
        _guard(pg)
        before = capture(pg)
        shared_graph = not member_question(pg, question_id)  # a member's confirmation stays on the question
    question, subs, proxies, observations = before
    if question is None:
        return {'error': '질문 없음'}
    lead, confirm, sub_verdicts = [], [], {}
    for sub in subs:
        scores = []
        for proxy in (p for p in proxies if p['sub_question_id'] == sub['id']):
            obs = [o for o in observations if o['proxy_id'] == proxy['id'] and o['direction'] is not None]
            obs.sort(key=lambda o: (o['observed_at'] is not None, o['observed_at'] or '', o['id']), reverse=True)
            if not obs:
                continue
            direction = obs[0]['direction']
            score = 0 if direction == 'flat' else (1 if direction == (proxy['yes_direction'] or 'up') else -1)
            scores.append(score)
            (lead if proxy['modality'] in questions._FAST else confirm).append(score)
        sub_verdicts[sub['id']] = questions._verdict(sum(scores), len(scores))
    lead_v = questions._verdict(sum(lead), len(lead))
    confirm_v = questions._verdict(sum(confirm), len(confirm))
    divergence = questions._divergence(lead_v, confirm_v)
    now_confirmed = confirm_v == 'leaning_yes' and divergence == 'aligned' and question['narrative_id'] is not None
    graph_before = None
    if now_confirmed and not question['edge_confirmed'] and shared_graph:
        with connect() as pg:
            _guard(pg)
            graph_before = capture_graph(pg, question['narrative_id'])
    changed = (lead_v, confirm_v, divergence) != (question['lead_verdict'], question['confirm_verdict'], question['divergence'])
    summary = question['verdict_summary']
    if changed:
        text = ' / '.join(f"{s['text']}: {questions._KO.get(sub_verdicts[s['id']], '미판정')}" for s in subs)
        prompt = questions._SUMMARY_PROMPT.format(q=question['text'], lead=questions._KO.get(lead_v),
                                                  confirm=questions._KO.get(confirm_v), subs=text)
        try:
            summary = run_llm(prompt, task='question.summarize').text.strip().split('\n')[0][:400] or None
        except Exception:
            summary = None
    with connect() as pg:
        _guard(pg)
        pg.execute('LOCK TABLE questions,sub_questions,proxy_registry,proxy_observations IN SHARE ROW EXCLUSIVE MODE')
        if capture(pg) != before:
            return {'status': 'stale'}
        edges_confirmed = 0
        if graph_before is not None:
            pg.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
            pg.execute('LOCK TABLE question_graph_overlay_rows,question_graph_overlay_relations,question_graph_overlay_evidence IN SHARE ROW EXCLUSIVE MODE')
            if capture_graph(pg, question['narrative_id']) != graph_before:
                return {'status': 'stale'}
            edge_ids = [r[0] for r in graph_before[1]]
            stamp = pg.execute("SELECT to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')").fetchone()[0]
            pg.execute("UPDATE question_graph_overlay_rows SET row_data=row_data || jsonb_build_object('obs_confirmed_at',%s::text,'obs_confirmed_qid',%s::bigint) "
                       "WHERE table_name='entity_relations' AND (row_data->>'id')::bigint=ANY(%s)", (stamp, question_id, edge_ids))
            updated = pg.execute("UPDATE question_graph_overlay_relations SET source_row=source_row || jsonb_build_object('obs_confirmed_at',%s::text,'obs_confirmed_qid',%s::bigint) "
                                 'WHERE id=ANY(%s)', (stamp, question_id, edge_ids))
            edges_confirmed = updated.rowcount
        for sub_id, verdict in sub_verdicts.items():
            pg.execute('UPDATE sub_questions SET verdict=%s WHERE id=%s', (verdict, sub_id))
        conviction = abs(sum(confirm)) / len(confirm) if confirm else None
        pg.execute("UPDATE questions SET lead_verdict=%s,confirm_verdict=%s,divergence=%s,verdict_summary=%s, "
                   "conviction=%s,edge_confirmed=%s,updated_at=to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS') WHERE id=%s",
                   (lead_v, confirm_v, divergence, summary, conviction, int(now_confirmed), question_id))
    return {'status': 'ok', 'lead_verdict': lead_v, 'confirm_verdict': confirm_v,
            'divergence': divergence, 'changed': changed, 'edges_confirmed': edges_confirmed}

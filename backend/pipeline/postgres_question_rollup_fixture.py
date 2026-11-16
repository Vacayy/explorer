"""Use the original verdict rules against a private PG question capture.

Question-associated graph edge confirmation is deliberately refused until a
shared graph writer is supplied. This module is not mounted to a user API.
"""
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_questions_fixture import _projection

INPUT_TABLES=('questions','sub_questions','proxy_registry','proxy_observations')


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
    def graph_needed(db,qid,narrative_id):
        raise NotImplementedError('Shared graph edge confirmation is not connected')
    with _projection(connect,writable=True) as factory:
        if _inputs(connect)!=before:return {'status':'stale'}
        result=questions.rollup(question_id,connection_factory=factory,summarizer=summarize,confirm_edges=graph_needed)
        if 'error' in result:return result
        db=factory()
        try:
            question=dict(db.execute('SELECT * FROM questions WHERE id=?',(question_id,)).fetchone())
            subs=[dict(r) for r in db.execute('SELECT * FROM sub_questions WHERE question_id=?',(question_id,))]
        finally:db.close()
    with connect() as pg:
        _guard(pg)
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
        current=pg.execute('''SELECT table_name,row_ordinal,row_data FROM question_capture_rows
            WHERE table_name=ANY(%s) ORDER BY table_name,row_ordinal''',(list(INPUT_TABLES),)).fetchall()
        if current!=before:return {'status':'stale'}
        for table,rows in (('questions',[question]),('sub_questions',subs)):
            for row in rows:
                changed=pg.execute('UPDATE question_capture_rows SET row_data=%s WHERE table_name=%s AND row_data->>\'id\'=%s',
                                   (Jsonb(row),table,str(row['id'])))
                if changed.rowcount!=1:raise ValueError('Question capture identity mismatch')
    return {'status':'ok',**result}

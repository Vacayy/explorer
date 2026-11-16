"""Isolated question decomposition persistence; not a complete create API.

Observation extraction and rollup are not implemented here, so this module is
not mounted to a user-facing route. The caller must explicitly supply an LLM.
"""
import json
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_questions_fixture import _projection


def decompose_and_stage(connect, text, *, run_llm, created_by='user', narrative_id=None, source_doc_id=None):
    if not text.strip():raise ValueError('질문이 비어 있습니다')
    raw=run_llm(questions._DECOMPOSE_PROMPT.format(question=text.strip()),task='question.decompose').text
    left,right=raw.find('{'),raw.rfind('}')
    if left<0 or right<left:raise ValueError('질문 분해 결과가 올바르지 않습니다')
    plan=json.loads(raw[left:right+1])
    if not isinstance(plan,dict) or not isinstance(plan.get('sub_questions'),list):
        raise ValueError('질문 분해 결과가 올바르지 않습니다')
    return stage_plan(connect,text,plan,created_by=created_by,narrative_id=narrative_id,source_doc_id=source_doc_id)


def stage_plan(connect,text,plan,*,created_by='user',narrative_id=None,source_doc_id=None):
    """Atomically append the original question and its model decomposition.

    This is a private building block. The original create flow also extracts
    observations and rolls up verdicts, which callers still need to implement.
    """
    if not text.strip() or not isinstance(plan,dict) or not isinstance(plan.get('sub_questions'),list):
        raise ValueError('Invalid decomposition')
    with connect() as pg:
        _guard(pg)
        # Guard the captured rows against concurrent direct PG updates as well
        # as other staging calls; no LLM call is made while holding this lock.
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
        with _projection(connect,writable=True) as factory:
            db=factory()
            try:
                qid=db.execute("INSERT INTO questions(text,narrative_id,source_doc_id,created_by,status,stock_code) VALUES(?,?,?,?,'tracking',NULL)",
                               (text.strip(),narrative_id,source_doc_id,created_by)).lastrowid
                ids={'questions':[qid], 'sub_questions':[], 'proxy_registry':[]}
                has_numeric=has_sentiment=False
                for sq in plan['sub_questions']:
                    sqid=db.execute('INSERT INTO sub_questions(question_id,text,falsifier) VALUES(?,?,?)',
                                    (qid,(sq.get('text') or '').strip(),(sq.get('falsifier') or '').strip() or None)).lastrowid
                    ids['sub_questions'].append(sqid)
                    for i,p in enumerate(sq.get('proxies',[])):
                        modality=p.get('modality') if p.get('modality') in ('numeric','sentiment','stance') else 'numeric'
                        direction=p.get('yes_direction') if p.get('yes_direction') in ('up','down') else 'up'
                        cur=db.execute('''INSERT OR IGNORE INTO proxy_registry(key,label,sub_question_id,modality,tickers,unit,extract_hint,yes_direction)
                            VALUES(?,?,?,?,?,?,?,?)''', (questions._slugify(p.get('label',''),qid,i),(p.get('label') or '프록시').strip(),sqid,modality,
                            (p.get('tickers') or '').strip() or None,(p.get('unit') or '').strip() or None,(p.get('extract_hint') or '').strip() or None,direction))
                        if cur.rowcount:ids['proxy_registry'].append(cur.lastrowid)
                        if modality=='numeric' and (p.get('tickers') or '').strip():has_numeric=True
                        elif modality=='sentiment':has_sentiment=True
                db.commit()
                for table,new_ids in ids.items():
                    if not new_ids:continue
                    columns=pg.execute('SELECT columns FROM question_capture_tables WHERE table_name=%s FOR UPDATE',(table,)).fetchone()[0]
                    offset=pg.execute('SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_capture_rows WHERE table_name=%s',(table,)).fetchone()[0]
                    for index,ident in enumerate(new_ids):
                        row=db.execute('SELECT * FROM '+table+' WHERE id=?',(ident,)).fetchone()
                        pg.execute('INSERT INTO question_capture_rows VALUES(%s,%s,%s)',(table,offset+index,Jsonb({key:row[key] for key in columns})))
                    pg.execute('UPDATE question_capture_tables SET row_count=row_count+%s WHERE table_name=%s',(len(new_ids),table))
                    seq=db.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
                    if seq:
                        pg.execute('''INSERT INTO question_capture_sequences VALUES(%s,%s)
                            ON CONFLICT(table_name) DO UPDATE SET sequence_value=GREATEST(question_capture_sequences.sequence_value,EXCLUDED.sequence_value)''',(table,seq[0]))
                return {'question_id':qid,'numeric_extraction_needed':has_numeric,'sentiment_extraction_needed':has_sentiment,'rollup_needed':True}
            finally:db.close()

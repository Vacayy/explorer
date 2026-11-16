"""Isolated question sentiment extraction using explicit PG search and LLM.

This module is not mounted to the application. Numeric transcript extraction,
rollup, and creation orchestration are still needed.
"""
import json
from datetime import datetime,timedelta,timezone
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_questions_fixture import _projection


def extract_sentiment(connect,question_id,*,search,run_llm,per_proxy_docs=8):
    """Extract only this question's sentiment, preserving the daily guard.

    The caller provides PG-backed search and a model recorder. Model calls run
    outside PG write locks; stale proxy/snapshot inputs are discarded.
    """
    today=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d')
    with _projection(connect) as factory:
        db=factory()
        try:
            rows=db.execute("""SELECT pr.id,pr.label,pr.extract_hint,pr.yes_direction
                FROM proxy_registry pr JOIN sub_questions sq ON sq.id=pr.sub_question_id
                JOIN questions q ON q.id=sq.question_id
                WHERE pr.active=1 AND pr.modality='sentiment' AND sq.question_id=?
                AND NOT EXISTS(SELECT 1 FROM proxy_observations po WHERE po.proxy_id=pr.id
                    AND po.source_type='corpus' AND po.source_id=?) ORDER BY pr.id""",(question_id,today)).fetchall()
            proxies=[dict(r) for r in rows]
        finally:db.close()
    extracted=0;stale=0
    for proxy in proxies:
        result=search((proxy['label']+' '+(proxy['extract_hint'] or '')).strip(),k=per_proxy_docs)
        doc_ids=list(dict.fromkeys(i['doc_id'] for i in result.items if i.get('doc_id') is not None))
        if not doc_ids:continue
        with connect() as pg:
            _guard(pg)
            metadata=pg.execute('SELECT snapshot_at,loaded_at,document_count,list_row_count,generation_id FROM snapshot_metadata').fetchone()
            proxy_row=pg.execute("SELECT row_data FROM question_capture_rows WHERE table_name='proxy_registry' AND row_data->>'id'=%s",(str(proxy['id']),)).fetchone()
            if not metadata or not proxy_row:raise ValueError('Missing snapshot or proxy')
            docs=pg.execute("""SELECT d.row_data->>'title',e.row_data->>'summary' FROM legacy_snapshot_rows d
                LEFT JOIN legacy_snapshot_rows e ON e.table_name='enrichments' AND e.row_data->>'doc_id'=d.row_data->>'id'
                WHERE d.table_name='raw_documents' AND d.row_data->>'id'=ANY(%s) ORDER BY d.row_ordinal,e.row_ordinal""",([str(i) for i in doc_ids],)).fetchall()
        snippets='\n'.join(f"- {(title or '')[:80]}: {(summary or '')[:200]}" for title,summary in docs)
        if not snippets.strip():continue
        try:
            raw=run_llm(questions._SENTIMENT_PROMPT.format(label=proxy['label'],hint=proxy['extract_hint'] or '',snippets=snippets[:8000]),task='proxy.sentiment').text
            result=json.loads(raw[raw.find('{'):raw.rfind('}')+1])
        except Exception:
            continue
        direction=result.get('direction') if result.get('direction') in ('up','down','flat') else None
        with connect() as pg:
            _guard(pg)
            pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
            pg.execute('LOCK TABLE legacy_snapshot_rows, snapshot_metadata IN SHARE MODE')
            current_meta=pg.execute('SELECT snapshot_at,loaded_at,document_count,list_row_count,generation_id FROM snapshot_metadata').fetchone()
            current_proxy=pg.execute("SELECT row_data FROM question_capture_rows WHERE table_name='proxy_registry' AND row_data->>'id'=%s",(str(proxy['id']),)).fetchone()
            current_docs=pg.execute("""SELECT d.row_data->>'title',e.row_data->>'summary' FROM legacy_snapshot_rows d
                LEFT JOIN legacy_snapshot_rows e ON e.table_name='enrichments' AND e.row_data->>'doc_id'=d.row_data->>'id'
                WHERE d.table_name='raw_documents' AND d.row_data->>'id'=ANY(%s) ORDER BY d.row_ordinal,e.row_ordinal""",([str(i) for i in doc_ids],)).fetchall()
            if current_meta!=metadata or current_proxy!=proxy_row or current_docs!=docs:
                stale+=1;continue
            with _projection(connect,writable=True) as factory:
                db=factory()
                try:
                    if db.execute("SELECT 1 FROM proxy_observations WHERE proxy_id=? AND source_type='corpus' AND source_id=?",(proxy['id'],today)).fetchone():continue
                    ident=db.execute("""INSERT INTO proxy_observations(proxy_id,source_type,source_id,observed_at,value_text,direction)
                        VALUES(?,'corpus',?,?,?,?)""",(proxy['id'],today,today,result.get('value_text'),direction)).lastrowid
                    db.commit()
                    cols=pg.execute("SELECT columns FROM question_capture_tables WHERE table_name='proxy_observations' FOR UPDATE").fetchone()[0]
                    row=db.execute('SELECT * FROM proxy_observations WHERE id=?',(ident,)).fetchone()
                    ordinal=pg.execute("SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_capture_rows WHERE table_name='proxy_observations'").fetchone()[0]
                    pg.execute("INSERT INTO question_capture_rows VALUES('proxy_observations',%s,%s)",(ordinal,Jsonb({c:row[c] for c in cols})))
                    pg.execute("UPDATE question_capture_tables SET row_count=row_count+1 WHERE table_name='proxy_observations'")
                    seq=db.execute("SELECT seq FROM sqlite_sequence WHERE name='proxy_observations'").fetchone()
                    if seq:pg.execute("""INSERT INTO question_capture_sequences VALUES('proxy_observations',%s)
                        ON CONFLICT(table_name) DO UPDATE SET sequence_value=GREATEST(question_capture_sequences.sequence_value,EXCLUDED.sequence_value)""",(seq[0],))
                    extracted+=1
                finally:db.close()
    return {'extracted':extracted,'stale':stale}

"""Isolated transcript proxy extraction; no operational service is changed.

Only question-side observations and scans are written. Projection into graph
observations and question rollup must be wired before exposing this to users.
"""
import json
from psycopg.types.json import Jsonb
from pipeline import transcript
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_questions_fixture import _projection


def _append(pg,db,table,rows):
    if not rows:return
    columns=pg.execute('SELECT columns FROM question_capture_tables WHERE table_name=%s FOR UPDATE',(table,)).fetchone()[0]
    offset=pg.execute('SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_capture_rows WHERE table_name=%s',(table,)).fetchone()[0]
    with pg.cursor() as cur:
        cur.executemany('INSERT INTO question_capture_rows VALUES(%s,%s,%s)',
                        ((table,offset+i,Jsonb({k:row[k] for k in columns})) for i,row in enumerate(rows)))
    pg.execute('UPDATE question_capture_tables SET row_count=row_count+%s WHERE table_name=%s',(len(rows),table))
    seq=db.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
    if seq:pg.execute('''INSERT INTO question_capture_sequences VALUES(%s,%s)
        ON CONFLICT(table_name) DO UPDATE SET sequence_value=GREATEST(question_capture_sequences.sequence_value,EXCLUDED.sequence_value)''',(table,seq[0]))


def extract_numeric(connect,question_id,*,run_llm,limit=40):
    """Use captured PG transcript data for the requested question only."""
    if not isinstance(limit,int) or not 1<=limit<=40:raise ValueError('invalid scan limit')
    with _projection(connect) as factory:
        db=factory()
        try:
            proxies=[dict(r) for r in db.execute('''SELECT pr.id,pr.key,pr.label,pr.tickers,pr.unit,pr.extract_hint
                FROM proxy_registry pr JOIN sub_questions sq ON sq.id=pr.sub_question_id
                WHERE pr.active=1 AND sq.question_id=? ORDER BY pr.id''',(question_id,))]
        finally:db.close()
    scanned=extracted=stale=0
    for proxy in proxies:
        tickers=[t.strip() for t in (proxy['tickers'] or '').split(',') if t.strip()]
        if not tickers:continue
        with connect() as pg:
            _guard(pg)
            metadata=pg.execute('SELECT snapshot_at,loaded_at,document_count,list_row_count,generation_id FROM snapshot_metadata').fetchone()
            proxy_row=pg.execute("SELECT row_data FROM question_capture_rows WHERE table_name='proxy_registry' AND row_data->>'id'=%s",(str(proxy['id']),)).fetchone()
            if not metadata or not proxy_row:raise ValueError('Missing snapshot or proxy')
            rows=pg.execute("""SELECT t.row_data,d.row_data FROM legacy_snapshot_rows t JOIN legacy_snapshot_rows d
                ON d.table_name='raw_documents' AND d.row_data->>'id'=t.row_data->>'raw_doc_id'
                WHERE t.table_name='transcripts' AND t.row_data->>'ticker'=ANY(%s)
                ORDER BY (t.row_data->>'fiscal_year')::integer DESC NULLS LAST,t.row_ordinal LIMIT %s""",(tickers,limit)).fetchall()
        for item,doc in rows:
            if scanned>=limit:break
            tid=item['id']
            with _projection(connect) as factory:
                db=factory()
                try:
                    exists=db.execute('''SELECT 1 FROM proxy_observations WHERE proxy_id=? AND transcript_id=?
                        UNION ALL SELECT 1 FROM proxy_scans WHERE proxy_id=? AND transcript_id=?''',(proxy['id'],tid,proxy['id'],tid)).fetchone()
                finally:db.close()
            if exists:continue
            scanned+=1
            try:
                raw=run_llm(transcript._PROXY_PROMPT.format(label=proxy['label'],hint=proxy['extract_hint'] or '',body=(doc.get('markdown') or '')[:40000]),task='proxy.extract').text
                value=json.loads(raw[raw.find('{'):raw.rfind('}')+1])
                if not isinstance(value,dict):raise ValueError('invalid extraction')
            except Exception:continue
            with connect() as pg:
                _guard(pg)
                pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
                pg.execute('LOCK TABLE legacy_snapshot_rows, snapshot_metadata IN SHARE MODE')
                current_meta=pg.execute('SELECT snapshot_at,loaded_at,document_count,list_row_count,generation_id FROM snapshot_metadata').fetchone()
                current_proxy=pg.execute("SELECT row_data FROM question_capture_rows WHERE table_name='proxy_registry' AND row_data->>'id'=%s",(str(proxy['id']),)).fetchone()
                current=pg.execute("""SELECT t.row_data,d.row_data FROM legacy_snapshot_rows t JOIN legacy_snapshot_rows d
                    ON d.table_name='raw_documents' AND d.row_data->>'id'=t.row_data->>'raw_doc_id'
                    WHERE t.table_name='transcripts' AND t.row_data->>'id'=%s""",(str(tid),)).fetchone()
                if current_meta!=metadata or current_proxy!=proxy_row or current!=(item,doc):stale+=1;continue
                with _projection(connect,writable=True) as factory:
                    db=factory()
                    try:
                        if db.execute('''SELECT 1 FROM proxy_observations WHERE proxy_id=? AND transcript_id=?
                            UNION ALL SELECT 1 FROM proxy_scans WHERE proxy_id=? AND transcript_id=?''',(proxy['id'],tid,proxy['id'],tid)).fetchone():continue
                        if not db.execute('SELECT 1 FROM transcripts WHERE id=?',(tid,)).fetchone():
                            columns=pg.execute("SELECT columns FROM question_capture_tables WHERE table_name='transcripts'").fetchone()[0]
                            db.execute('INSERT INTO transcripts('+','.join('"'+c.replace('"','""')+'"' for c in columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(item.get(c) for c in columns))
                            transcript_rows=[db.execute('SELECT * FROM transcripts WHERE id=?',(tid,)).fetchone()]
                        else:transcript_rows=[]
                        db.execute('INSERT OR IGNORE INTO proxy_scans(proxy_id,transcript_id) VALUES(?,?)',(proxy['id'],tid))
                        scan_rows=[db.execute('SELECT * FROM proxy_scans WHERE proxy_id=? AND transcript_id=?',(proxy['id'],tid)).fetchone()]
                        obs_rows=[]
                        if value.get('found'):
                            oid=db.execute('''INSERT INTO proxy_observations(proxy_id,transcript_id,source_type,source_id,observed_at,value_num,value_text,direction)
                                VALUES(?,?,'transcript',?,?,?,?,?)''',(proxy['id'],tid,str(tid),item.get('call_date'),value.get('value_num'),value.get('value_text'),value.get('direction'))).lastrowid
                            obs_rows=[db.execute('SELECT * FROM proxy_observations WHERE id=?',(oid,)).fetchone()]
                        db.commit()
                        _append(pg,db,'transcripts',transcript_rows);_append(pg,db,'proxy_scans',scan_rows);_append(pg,db,'proxy_observations',obs_rows)
                        if obs_rows:extracted+=1
                    finally:db.close()
    return {'extracted':extracted,'scanned':scanned,'stale':stale,'graph_projection_required':True}


def project_numeric_observations(connect):
    """Apply the original entity-observation projection inside this candidate.

    The complete observations table and transcript-follow mapping are captured
    with the questions, and callers must route future readers to this PG copy.
    """
    with connect() as pg:
        _guard(pg)
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
        with _projection(connect,writable=True) as factory:
            db=factory()
            try:
                existing={r[0] for r in db.execute('SELECT id FROM observations')}
                db.execute('''INSERT OR IGNORE INTO observations(entity_id,date,metric,value,unit,source)
                    SELECT tf.entity_id,po.observed_at,pr.key,po.value_num,pr.unit,'proxy:transcript'
                    FROM proxy_observations po JOIN transcripts t ON t.id=po.transcript_id
                    JOIN transcript_follow tf ON tf.ticker=t.ticker JOIN proxy_registry pr ON pr.id=po.proxy_id
                    WHERE po.source_type='transcript' AND po.value_num IS NOT NULL
                    AND tf.entity_id IS NOT NULL AND po.observed_at IS NOT NULL''')
                rows=[r for r in db.execute('SELECT * FROM observations ORDER BY id') if r['id'] not in existing]
                db.commit();_append(pg,db,'observations',rows)
                return {'projected':len(rows)}
            finally:db.close()


def entity_observations(connect,entity_id):
    """Read the same candidate observation records used by projection."""
    with _projection(connect) as factory:
        db=factory()
        try:return [dict(r) for r in db.execute('SELECT * FROM observations WHERE entity_id=? ORDER BY date,id',(entity_id,))]
        finally:db.close()

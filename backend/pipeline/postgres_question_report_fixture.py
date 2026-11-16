"""Isolated question report generation with explicit unresolved call tracking.

The report is only the first step. Scenario generation and graph writes must be
connected before a user-facing synthesis endpoint may invoke this module.
"""
from uuid import uuid4
from pipeline import question_report
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_questions_fixture import _projection
from pipeline.postgres_question_numeric_fixture import _append


def generate_report(connect,question_id,*,run_llm,refresh=False):
    """Generate or reuse a report; retain unknown external calls after crashes."""
    token=uuid4()
    with connect() as pg:
        _guard(pg)
        pg.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'question-report:{question_id}',))
        if pg.execute("SELECT 1 FROM question_report_attempts WHERE question_id=%s AND status IN ('running','unknown')",(question_id,)).fetchone():
            return {'status':'unresolved'}
        # Freeze inputs while preparing the immutable prompt, then release the
        # table lock before the potentially expensive external model call.
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE MODE')
        with _projection(connect) as factory:
            db=factory()
            try:
                evidence=question_report._gather(db,question_id)
                if not evidence:return {'status':'not_found'}
                if not question_report._has_material(evidence):return {'status':'empty'}
                digest=question_report._hash(evidence)
                cached=question_report._latest_report(db,question_id)
                if cached and cached['inputs_hash']==digest and not refresh:
                    has_scenario=db.execute('SELECT 1 FROM scenarios WHERE question_id=?',(question_id,)).fetchone() is not None
                    return {'status':'cached','report':{'body':cached['body'],'created_at':cached['created_at']},'scenario_required':not has_scenario}
            finally:db.close()
        pg.execute("INSERT INTO question_report_attempts(token,question_id,input_hash,status) VALUES(%s,%s,%s,'running')",(token,question_id,digest))
    body=question_report._generate_report(evidence,run_llm=run_llm)
    if not body:
        with connect() as pg:
            _guard(pg);pg.execute("UPDATE question_report_attempts SET status='unknown',finished_at=now() WHERE token=%s AND status='running'",(token,))
        return {'status':'unresolved'}
    with connect() as pg:
        _guard(pg)
        pg.execute('LOCK TABLE question_capture_rows, question_capture_tables, question_capture_sequences IN SHARE ROW EXCLUSIVE MODE')
        row=pg.execute('SELECT status FROM question_report_attempts WHERE token=%s FOR UPDATE',(token,)).fetchone()
        if not row or row[0]!='running':return {'status':'unresolved'}
        with _projection(connect,writable=True) as factory:
            db=factory()
            try:
                current=question_report._gather(db,question_id)
                # Compare all prompt inputs, not just the coarse freshness hash.
                if current!=evidence:
                    pg.execute("UPDATE question_report_attempts SET status='stale',finished_at=now() WHERE token=%s",(token,))
                    return {'status':'stale'}
                ident=db.execute('INSERT INTO question_reports(question_id,body,inputs_hash,model) VALUES(?,?,?,?)',
                    (question_id,body,digest,f'claude-code/{question_report.REPORT_MODEL}')).lastrowid
                report=db.execute('SELECT * FROM question_reports WHERE id=?',(ident,)).fetchone()
                db.commit();_append(pg,db,'question_reports',[report])
                pg.execute("UPDATE question_report_attempts SET status='completed',finished_at=now() WHERE token=%s",(token,))
                return {'status':'report_ready','report':{'body':body,'created_at':report['created_at']},'scenario_required':True}
            finally:db.close()

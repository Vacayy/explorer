"""Assemble question creation against the disposable single-path PG fixture.

The caller supplies the model and search. This internal function does not
retry model calls or publish an unauthenticated endpoint.
"""
import hashlib
import json
import uuid
from psycopg.types.json import Jsonb
from pipeline import questions
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_question_create_fixture import stage_plan_native
from pipeline.postgres_question_numeric_fixture import extract_numeric_native, project_numeric_observations_native
from pipeline.postgres_question_sentiment_fixture import extract_sentiment_native
from pipeline.postgres_question_rollup_fixture import rollup_question_native


class QuestionRunUnresolved(ValueError):
    def __init__(self, run_id):
        super().__init__('같은 질문의 이전 작업을 확인해 주세요')
        self.run_id = str(run_id)


class QuestionModelUncertain(RuntimeError):
    def __init__(self, run_id):
        super().__init__('질문 분해 결과를 확인하지 못했습니다')
        self.run_id = str(run_id)


def initialize_creation_runs(connect):
    """Create the journal once in an explicitly disposable fixture."""
    with connect() as pg:
        _guard(pg)
        if pg.execute("SELECT to_regclass('question_creation_runs')").fetchone()[0] is not None:
            raise ValueError('Creation journal already exists')
        pg.execute("CREATE TABLE question_creation_runs (id UUID PRIMARY KEY,request_hash TEXT NOT NULL, "
                   "question_id BIGINT,status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed','unknown')), "
                   "steps JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),finished_at TIMESTAMPTZ)")
        pg.execute("CREATE UNIQUE INDEX question_creation_unresolved ON question_creation_runs(request_hash) "
                   "WHERE status IN ('running','unknown')")


def _begin_run(connect, text, created_by, narrative_id, source_doc_id, stock_code=None, question_id=None):
    key = [text.strip(), created_by, narrative_id, source_doc_id] + ([stock_code] if stock_code else []) \
        + (['approve', question_id] if question_id is not None else [])
    request = json.dumps(key, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(request.encode()).hexdigest()
    run_id = uuid.uuid4()
    with connect() as pg:
        _guard(pg)
        pg.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (digest,))
        existing = pg.execute("SELECT id FROM question_creation_runs WHERE request_hash=%s AND status IN ('running','unknown')", (digest,)).fetchone()
        if existing:
            raise QuestionRunUnresolved(existing[0])
        pg.execute("INSERT INTO question_creation_runs(id,request_hash,status) VALUES(%s,%s,'running')", (run_id, digest))
    return run_id


def _record_run(connect, run_id, steps, status='running'):
    with connect() as pg:
        _guard(pg)
        updated = pg.execute("UPDATE question_creation_runs SET steps=%s,status=%s, "
                             "finished_at=CASE WHEN %s='running' THEN NULL ELSE now() END "
                             "WHERE id=%s AND status='running'", (Jsonb(steps), status, status, run_id))
        if updated.rowcount != 1:
            raise ValueError('Question creation run is unavailable')


def create_question_native(connect, text, *, run_llm, search, created_by='user', narrative_id=None,
                           source_doc_id=None, numeric_limit=40, stock_code=None, hint='', question_id=None,
                           on_staged=None):
    """stock_code ties a thesis/watch question to a stock; hint is added to the decomposition prompt only (as legacy).
    question_id decomposes an existing proposed question (approve) instead of adding one."""
    if not text.strip():
        raise ValueError('질문이 비어 있습니다')
    run_id = _begin_run(connect, text, created_by, narrative_id, source_doc_id, stock_code, question_id)
    steps = {}
    try:
        raw = run_llm(questions._DECOMPOSE_PROMPT.format(question=text.strip() + hint), task='question.decompose').text
    except Exception as exc:
        _record_run(connect, run_id, {'decompose': {'status': 'unknown'}}, 'unknown')
        raise QuestionModelUncertain(run_id) from exc
    try:
        left, right = raw.find('{'), raw.rfind('}')
        if left < 0 or right < left:
            raise ValueError('질문 분해 결과가 올바르지 않습니다')
        plan = json.loads(raw[left:right+1])
        if not isinstance(plan, dict) or not isinstance(plan.get('sub_questions'), list):
            raise ValueError('질문 분해 결과가 올바르지 않습니다')
        stage = stage_plan_native(connect, text, plan, created_by=created_by, narrative_id=narrative_id,
                                  source_doc_id=source_doc_id, run_id=run_id, stock_code=stock_code,
                                  question_id=question_id)
    except Exception:
        _record_run(connect, run_id, {'decompose': {'status': 'failed'}}, 'failed')
        raise
    qid = stage['question_id']
    if on_staged is not None:
        on_staged(qid)  # e.g. its owner, before the long extraction steps
    steps = {'decompose': {'status': 'ok'}}
    _record_run(connect, run_id, steps)

    def attempt(name, fn):
        try:
            result = fn()
            status = 'partial' if result.get('failed') or result.get('stale') else 'ok'
            steps[name] = {'status': status, 'result': result}
        except Exception as exc:
            # The saved question is preserved and no model request is retried.
            steps[name] = {'status': 'failed', 'error_type': type(exc).__name__}
        _record_run(connect, run_id, steps)

    if stage['numeric_extraction_needed']:
        attempt('numeric', lambda: extract_numeric_native(connect, qid, run_llm=run_llm, limit=numeric_limit))
        attempt('graph_observations', lambda: project_numeric_observations_native(connect, question_id=qid))
    else:
        steps['numeric'] = {'status': 'not_needed'}
    if stage['sentiment_extraction_needed']:
        attempt('sentiment', lambda: extract_sentiment_native(connect, qid, search=search, run_llm=run_llm))
    else:
        steps['sentiment'] = {'status': 'not_needed'}
    attempt('rollup', lambda: rollup_question_native(connect, qid, run_llm=run_llm))
    if steps['rollup']['status'] == 'ok' and steps['rollup']['result'].get('status') == 'stale':
        steps['rollup']['status'] = 'stale'
    final = 'partial' if any(step['status'] in ('failed', 'partial', 'stale') for step in steps.values()) else 'completed'
    _record_run(connect, run_id, steps, final)
    return {'question_id': qid, 'run_id': str(run_id), 'status': final, 'steps': steps}

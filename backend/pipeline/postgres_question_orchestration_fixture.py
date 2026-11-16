"""Assemble question creation against the disposable single-path PG fixture.

The caller supplies the model and search. This internal function does not
retry model calls or publish an unauthenticated endpoint.
"""
import json
from pipeline import questions
from pipeline.postgres_question_create_fixture import stage_plan_native
from pipeline.postgres_question_numeric_fixture import extract_numeric_native, project_numeric_observations_native
from pipeline.postgres_question_sentiment_fixture import extract_sentiment_native
from pipeline.postgres_question_rollup_fixture import rollup_question_native


def create_question_native(connect, text, *, run_llm, search, created_by='user', narrative_id=None,
                           source_doc_id=None, numeric_limit=40):
    if not text.strip():
        raise ValueError('질문이 비어 있습니다')
    raw = run_llm(questions._DECOMPOSE_PROMPT.format(question=text.strip()), task='question.decompose').text
    left, right = raw.find('{'), raw.rfind('}')
    if left < 0 or right < left:
        raise ValueError('질문 분해 결과가 올바르지 않습니다')
    plan = json.loads(raw[left:right+1])
    if not isinstance(plan, dict) or not isinstance(plan.get('sub_questions'), list):
        raise ValueError('질문 분해 결과가 올바르지 않습니다')
    stage = stage_plan_native(connect, text, plan, created_by=created_by,
                              narrative_id=narrative_id, source_doc_id=source_doc_id)
    qid = stage['question_id']
    steps = {}

    def attempt(name, fn):
        try:
            result = fn()
            status = 'partial' if result.get('failed') or result.get('stale') else 'ok'
            steps[name] = {'status': status, 'result': result}
        except Exception as exc:
            # The saved question is preserved and no model request is retried.
            steps[name] = {'status': 'failed', 'error_type': type(exc).__name__}

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
    return {'question_id': qid, 'steps': steps}

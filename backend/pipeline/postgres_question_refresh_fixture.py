"""Daily question refresh on the PG ledger (the launchd `questions` job, single-path preview).

Same steps and budgets as `questions.refresh_all`, through the native PG paths:
numeric transcript observations, corpus sentiment, numeric graph projection,
then re-judging every tracking question. The collector SQLite never judges
questions. Each re-judgment writes only verdict fields and only if nothing it
read changed meanwhile (`rollup_question_native` returns `stale` otherwise), so a
user edit made during the run wins and the question is judged again next run.
Not connected: narrative auto-proposal (flag off by default) and the Telegram
thesis/reason alerts that follow the legacy job.
"""
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_question_numeric_fixture import extract_numeric_native, project_numeric_observations_native
from pipeline.postgres_question_rollup_fixture import rollup_question_native
from pipeline.postgres_question_sentiment_fixture import extract_sentiment_native

NUMERIC_LIMIT = 40     # legacy extract_proxies(limit=40)
SENTIMENT_BUDGET = 20  # legacy extract_sentiment_proxies(budget=20)


def refresh_all_native(connect, *, run_llm, search):
    with connect() as pg:
        _guard(pg)
        ids = [row[0] for row in pg.execute("SELECT id FROM questions WHERE status='tracking' ORDER BY id")]
    out = {'numeric': 0, 'sentiment': 0, 'projected': 0, 'rerolled': 0, 'stale': [], 'failed': []}
    remaining = NUMERIC_LIMIT
    for question_id in ids:
        if remaining > 0:
            try:
                result = extract_numeric_native(connect, question_id, run_llm=run_llm, limit=remaining)
                out['numeric'] += result['extracted']
                remaining -= result['scanned']
            except Exception as exc:  # noqa: BLE001 - one question must not stop the others
                out['failed'].append((question_id, 'numeric', type(exc).__name__))
        if out['sentiment'] < SENTIMENT_BUDGET:
            try:
                out['sentiment'] += extract_sentiment_native(connect, question_id, search=search, run_llm=run_llm)['extracted']
            except Exception as exc:  # noqa: BLE001
                out['failed'].append((question_id, 'sentiment', type(exc).__name__))
    out['projected'] = project_numeric_observations_native(connect)['projected']
    for question_id in ids:
        try:
            result = rollup_question_native(connect, question_id, run_llm=run_llm)
        except Exception as exc:  # noqa: BLE001
            out['failed'].append((question_id, 'rollup', type(exc).__name__))
            continue
        if result.get('status') == 'stale':
            out['stale'].append(question_id)
        else:
            out['rerolled'] += 1
    return out

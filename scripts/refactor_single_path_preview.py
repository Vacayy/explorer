"""Private fixture: existing document, conversation and study routes share PG.

Never expose this unauthenticated experimental app to a public interface.
The imported document app validates the disposable fixture DSN and schema.
"""
import os
import threading

import psycopg
import uvicorn

os.environ['REFACTOR_LEXICAL_ONLY'] = '0'
os.environ['REFACTOR_ALLOW_STALE_VECTORS'] = '1'
from refactor_document_ui import app, factory
import refactor_document_ui as document_ui
from pipeline.postgres_chat_tools import PostgreSQLChatTools
from pipeline.postgres_chunk_rag import PostgreSQLChunkRAG
from pipeline.postgres_conversations import PostgreSQLConversations
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_study_actions_fixture import StudyActionsFixture
from pipeline.postgres_study_fixture import StudyFixture
from pipeline.postgres_study_projects_fixture import StudyProjectsFixture
from pipeline.postgres_study_turn_fixture import StudyTurnsFixture
from routers.postgres_chat_fixture import create_router as chat_router
from routers.postgres_questions_fixture import create_router as questions_router
from routers.postgres_questions_fixture import create_proxy_router as proxy_extract_router
from routers.postgres_video_fixture import create_router as video_router
from routers.postgres_study_fixture import create_router as study_router
from routers.postgres_study_projects_fixture import create_router as project_router
from pipeline.postgres_legacy_projection import LegacyProjection
from routers.postgres_legacy_read_fixture import install as install_legacy_reads
from routers.postgres_owner_portfolio_fixture import install as install_owner_portfolio
from routers.postgres_owner_records_fixture import install as install_owner_records
from routers.postgres_owner_legacy_fixture import install as install_owner_legacy
from routers.postgres_claims_fixture import install as install_claims
from routers.postgres_owner_overrides_fixture import install as install_owner_overrides
from routers.postgres_collector_requests_fixture import install as install_collector_requests

if os.environ.get('REFACTOR_FEED_POINTER_SCHEMA'):
    raise RuntimeError('Single-path preview does not permit a separate feed pointer')

class LazyHybridIndex:
    """Build the disposable document index only when a search needs it."""
    def __init__(self):
        self.lock = document_ui.search_lock

    def get(self):
        with self.lock:
            if document_ui.search_index is None:
                with factory() as connection:
                    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    document_ui.search_index = SearchSnapshot.from_postgres(connection, allow_stale=True)
            return document_ui.search_index

    @property
    def generation(self):
        return self.get().generation

    @property
    def excluded_vectors(self):
        return self.get().excluded_vectors

    def search(self, *args, **kwargs):
        return self.get().search(*args, **kwargs)

    def close(self):
        with self.lock:
            if document_ui.search_index is not None:
                document_ui.search_index.close()
                document_ui.search_index = None


owner = os.environ.get('TELEGRAM_CHAT_ID') or None
store = PostgreSQLConversations(factory)
search = LazyHybridIndex()
def query_vector(query):
    from pipeline.search import _get_model, _serialize
    with document_ui.search_lock:
        return _serialize(next(iter(_get_model(local_files_only=True).embed([query]))))


def legacy_search(q, k=20):
    """The legacy `pipeline.search.search` contract ([{doc_id, score}]) over the candidate's hybrid index."""
    return search.search(q, vector=query_vector(q), k=max(1, min(k, 100)))


import sys  # noqa: E402 - legacy modules that bound `search` at import read the candidate index too
import pipeline.search as legacy_search_module  # noqa: E402
for module in list(sys.modules.values()):
    if getattr(module, 'search', None) is legacy_search_module.search and module is not legacy_search_module:
        module.search = legacy_search
legacy_search_module.search = legacy_search


def legacy_embeddings(conn, doc_ids):
    """The legacy `consolidation._embeddings` contract ({doc_id: vector}) from the candidate's PG vectors."""
    import struct
    with factory() as connection:
        rows = connection.execute('SELECT document_id,embedding FROM document_embeddings WHERE document_id=ANY(%s)',
                                  (list(doc_ids),)).fetchall()
    return {ident: list(struct.unpack(f'{len(blob) // 4}f', blob)) for ident, blob in rows}


import pipeline.consolidation as legacy_consolidation  # noqa: E402 - doc_vec is not in the projection
import pipeline.falsifiers  # noqa: E402,F401 - binds `_embeddings` at import
for module in list(sys.modules.values()):
    if getattr(module, '_embeddings', None) is legacy_consolidation._embeddings and module is not legacy_consolidation:
        module._embeddings = legacy_embeddings
legacy_consolidation._embeddings = legacy_embeddings


import logging  # noqa: E402
import pipeline.scenario as legacy_scenario  # noqa: E402
_build_scenario = legacy_scenario.build_scenario


def build_scenario_logged(*args, **kwargs):
    # The legacy route turns any failure into status 'error'; keep the reason in the log.
    try:
        return _build_scenario(*args, **kwargs)
    except Exception:
        logging.getLogger('preview.scenario').exception('Scenario build failed')
        raise


legacy_scenario.build_scenario = build_scenario_logged


import pipeline.chart_structure as legacy_chart  # noqa: E402
import pipeline.market_analysis.model as legacy_model  # noqa: E402
import pipeline.market_analysis.refine as legacy_refine  # noqa: E402
STRUCTURED_TASKS = {legacy_refine.SYSTEM: 'analysis.refine', legacy_chart.ASSIST_SYSTEM: 'chart.company_assist'}


def structured_call_via_llm(system, context, schema, *, budget, timeout, model=None):
    # The legacy structured_call needs the Claude CLI; the same prompt, context and schema go through a
    # registered llm.run task (Codex fallback while Claude is unavailable). Unknown callers are refused.
    import json
    import re
    from pipeline import llm
    task = STRUCTURED_TASKS.get(system)
    if task is None:
        raise legacy_model.ModelError('이 구조화 호출은 후보에서 아직 실행하지 않습니다.', 0)
    try:
        result = llm.run(json.dumps(context, ensure_ascii=False), task=task, system=system, json_schema=schema,
                         record_call=lambda *args: None)
        match = re.search(r'\{.*\}', result.text, re.S)
        return json.loads(match.group(0) if match else result.text), float(result.cost_usd or 0)
    except legacy_model.ModelError:
        raise
    except Exception as exc:  # the legacy routes answer ModelError as 502 / an unknown company
        raise legacy_model.ModelError(f'모델 호출 실패: {type(exc).__name__}', 0) from exc


legacy_model.structured_call = structured_call_via_llm
legacy_refine.structured_call = structured_call_via_llm


class SnapshotMetadata:
    connect = staticmethod(factory)

    @property
    def generation(self):
        return search.generation


entity_resolver = PostgreSQLChunkRAG(SnapshotMetadata(), None)
EVIDENCE_WAIT_SECONDS = float(os.environ.get('REFACTOR_EVIDENCE_WAIT_SECONDS', '90'))


def worker_tool(name, args):
    # AI-answer tools (evidence search, causal graph, cached narratives) run unchanged in the compute worker
    # (search models too large for this process). A job not done in time is marked failed and the tool falls
    # back (the index search for evidence).
    import time
    from pipeline.chat_tools import ToolResult
    from pipeline.postgres_retrieval_jobs import enqueue
    with factory() as conn:
        ident = enqueue(conn, 'chat_tool', f"{name}: {args.get('query') or args.get('entity') or args.get('topic') or ''}"[:200],
                        {'name': name, 'args': args})
    deadline = time.monotonic() + EVIDENCE_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(.3)
        with factory() as conn:
            status, result, error = conn.execute('SELECT status,result,error FROM retrieval_jobs WHERE id=%s',
                                                 (ident,)).fetchone()
        if status == 'done':
            return ToolResult(name, result.get('args') or args, result['items'], result.get('note'),
                              assumed=result.get('assumed') or [])
        if status == 'failed':
            logging.getLogger('preview.evidence').warning('Tool job %s (%s) failed: %s', ident, name, error)
            return None
    with factory() as conn:
        conn.execute("UPDATE retrieval_jobs SET status='failed',error='timed out in the API',updated_at=now() "
                     "WHERE id=%s AND status='queued'", (ident,))
    logging.getLogger('preview.evidence').warning('Tool job %s (%s) timed out', ident, name)
    return None


tools = PostgreSQLChatTools(factory, search, query_vector=query_vector,
                            entity_resolver=entity_resolver.entity_scope, worker_tool=worker_tool)
turns = StudyTurnsFixture(factory, store, tools, owner_chat_id=owner)
actions = StudyActionsFixture(factory, store, tools, owner_chat_id=owner)
app.include_router(chat_router(store, tools, owner_chat_id=owner))
def question_model(prompt, *, task):
    from pipeline import llm
    return llm.run(prompt, task=task, record_call=lambda *args: None)


def question_search(query, *, k):
    return tools.run_tool({'name': 'search_docs', 'args': {'query': query, 'k': k}})


app.include_router(questions_router(factory, run_llm=question_model, search=question_search,
                                    projection=lambda: legacy_projection))
app.include_router(proxy_extract_router(factory, run_llm=question_model))
app.include_router(video_router(factory, search_lock=document_ui.search_lock, invalidate_search=search.close))
app.include_router(study_router(StudyFixture(factory), turns=turns, actions=actions))
app.include_router(project_router(StudyProjectsFixture(factory), turns=turns))
# The projection builder container builds the legacy projection and re-embeds changed documents
# (pipeline.postgres_legacy_projection_builder); this process only switches files and lets the
# next search rebuild over the new vectors.
legacy_projection = LegacyProjection(factory, '/projection', on_change=search.close, external=True)
install_legacy_reads(app, legacy_projection,
                     database_host=psycopg.conninfo.conninfo_to_dict(os.environ['REFACTOR_POSTGRES_DSN'])['host'])
install_owner_portfolio(app, factory, run_llm=question_model, search=question_search)  # after the legacy reads it replaces
# Model-assisted reads with no stored result: the unchanged legacy handlers, structured calls via llm.run.
from fastapi.routing import APIRoute  # noqa: E402
from routers import analysis as legacy_analysis_router, chart_structure as legacy_chart_router  # noqa: E402
from routers import spine_feed as legacy_feed_router  # noqa: E402
for legacy_router, path in ((legacy_chart_router.router, '/api/spine/chart-structure/interpret'),
                            (legacy_analysis_router.router, '/api/analysis/refine'),
                            (legacy_feed_router.router, '/api/spine/feed/company-evidence/summary')):
    app.router.routes.extend(route for route in legacy_router.routes
                             if isinstance(route, APIRoute) and route.path == path and 'POST' in route.methods)
install_owner_records(app, factory, document_ui.timeline_reader, legacy_projection)
install_owner_legacy(app, legacy_projection, factory, run_llm=question_model, search=question_search)
install_claims(app, factory, question_model)  # claims extraction here, related documents in the compute worker
install_owner_overrides(app, legacy_projection, factory)  # admin decisions over collected rows
install_collector_requests(app, factory)  # collection buttons: recorded, never run here
threading.Thread(target=legacy_projection.path, daemon=True).start()  # warm before the first home visit


@app.on_event('shutdown')
def close_search():
    search.close()


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)

"""Private fixture: existing document, conversation and study routes share PG.

Never expose this unauthenticated experimental app to a public interface.
The imported document app validates the disposable fixture DSN and schema.
"""
import os

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
from routers.postgres_video_fixture import create_router as video_router
from routers.postgres_study_fixture import create_router as study_router
from routers.postgres_study_projects_fixture import create_router as project_router

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


class SnapshotMetadata:
    connect = staticmethod(factory)

    @property
    def generation(self):
        return search.generation


entity_resolver = PostgreSQLChunkRAG(SnapshotMetadata(), None)
tools = PostgreSQLChatTools(factory, search, query_vector=query_vector,
                            entity_resolver=entity_resolver.entity_scope)
turns = StudyTurnsFixture(factory, store, tools, owner_chat_id=owner)
actions = StudyActionsFixture(factory, store, tools, owner_chat_id=owner)
app.include_router(chat_router(store, tools, owner_chat_id=owner))
def question_model(prompt, *, task):
    from pipeline import llm
    return llm.run(prompt, task=task, record_call=lambda *args: None)


def question_search(query, *, k):
    return tools.run_tool({'name': 'search_docs', 'args': {'query': query, 'k': k}})


app.include_router(questions_router(factory, run_llm=question_model, search=question_search))
app.include_router(video_router(factory, search_lock=document_ui.search_lock, invalidate_search=search.close))
app.include_router(study_router(StudyFixture(factory), turns=turns, actions=actions))
app.include_router(project_router(StudyProjectsFixture(factory), turns=turns))


@app.on_event('shutdown')
def close_search():
    search.close()


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)

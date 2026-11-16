"""Private fixture: existing document, conversation and study routes share PG.

Never expose this unauthenticated experimental app to a public interface.
The imported document app validates the disposable fixture DSN and schema.
"""
import os
import threading

import uvicorn

from refactor_document_ui import app, factory
from pipeline.postgres_chat_tools import PostgreSQLChatTools
from pipeline.postgres_conversations import PostgreSQLConversations
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_study_actions_fixture import StudyActionsFixture
from pipeline.postgres_study_fixture import StudyFixture
from pipeline.postgres_study_projects_fixture import StudyProjectsFixture
from pipeline.postgres_study_turn_fixture import StudyTurnsFixture
from routers.postgres_chat_fixture import create_router as chat_router
from routers.postgres_study_fixture import create_router as study_router
from routers.postgres_study_projects_fixture import create_router as project_router

if os.environ.get('REFACTOR_FEED_POINTER_SCHEMA'):
    raise RuntimeError('Single-path preview does not permit a separate feed pointer')

class LazyLexicalIndex:
    """Build the disposable keyword index only when a search needs it."""
    def __init__(self):
        self.lock = threading.RLock()
        self.index = None

    def get(self):
        with self.lock:
            if self.index is None:
                with factory() as connection:
                    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    self.index = SearchSnapshot.from_postgres(connection, lexical_only=True)
            return self.index

    @property
    def generation(self):
        return self.get().generation

    def search(self, *args, **kwargs):
        return self.get().search(*args, **kwargs)

    def close(self):
        if self.index is not None:
            self.index.close()


owner = os.environ.get('TELEGRAM_CHAT_ID') or None
store = PostgreSQLConversations(factory)
search = LazyLexicalIndex()
tools = PostgreSQLChatTools(factory, search, allow_lexical_only=True)
turns = StudyTurnsFixture(factory, store, tools, owner_chat_id=owner)
actions = StudyActionsFixture(factory, store, tools, owner_chat_id=owner)
app.include_router(chat_router(store, tools, owner_chat_id=owner))
app.include_router(study_router(StudyFixture(factory), turns=turns, actions=actions))
app.include_router(project_router(StudyProjectsFixture(factory), turns=turns))


@app.on_event('shutdown')
def close_search():
    search.close()


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)

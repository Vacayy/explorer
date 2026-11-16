"""Fork a private chat preview without copying the shared document snapshot."""
import re
from pathlib import Path

from psycopg import sql
from pipeline.postgres_conversations import import_sqlite_conversations
from pipeline.postgres_graph_fixture import _guard


CHAT_TABLES = frozenset(('conversations', 'chat_messages', 'chat_entity_links',
                         'conversation_import_unresolved_docs', 'conversation_import_origin', 'chat_model_calls'))


def fork_chat_preview(source, target, base_schema):
    """Import current SQLite chat into a new fixture with read-only base views.

    The caller creates an empty fixture schema and keeps the base snapshot
    immutable. This is a preview, not a write freeze or operational cutover.
    """
    _guard(target)
    current = target.execute('SELECT current_schema()').fetchone()[0]
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', base_schema or '') or base_schema == current:
        raise ValueError('Separate fixture base required')
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('An active query-only SQLite snapshot is required')
    with target.transaction():
        if target.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                          "WHERE n.nspname=%s AND c.relkind IN ('r','p','v','m'))", (current,)).fetchone()[0]:
            raise ValueError('Empty target schema required')
        tables = {r[0] for r in target.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (base_schema,))}
        if not {'document_projection', 'legacy_snapshot_rows', 'snapshot_metadata'} <= tables:
            raise ValueError('Complete base snapshot required')
        for name in sorted(tables - CHAT_TABLES):
            # UNION ALL keeps PostgreSQL from making the view automatically updatable.
            target.execute(sql.SQL('CREATE VIEW {} AS SELECT * FROM {}.{} UNION ALL '
                                   'SELECT * FROM {}.{} WHERE FALSE').format(
                sql.Identifier(name), sql.Identifier(base_schema), sql.Identifier(name),
                sql.Identifier(base_schema), sql.Identifier(name)))
        if target.execute("SELECT EXISTS(SELECT 1 FROM information_schema.views WHERE table_schema=%s "
                          "AND is_updatable <> 'NO')", (current,)).fetchone()[0]:
            raise ValueError('Base views must be read-only')
        target.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/conversation_store.sql').read_text())
        return import_sqlite_conversations(source, target)

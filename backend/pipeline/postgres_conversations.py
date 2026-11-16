"""Experimental PG conversation persistence for a single document snapshot.

The caller supplies a connection scoped to the same schema as
``document_projection``. This module does not start a model or change the
running service; authentication and model orchestration remain caller duties.
"""
import json

from psycopg.rows import dict_row


class ConversationNotFound(LookupError):
    pass


class DocumentNotFound(LookupError):
    pass


class PostgreSQLConversations:
    def __init__(self, connect):
        self.connect = connect

    @staticmethod
    def _owned(cursor, conversation_id, owner_chat_id, *, lock=False):
        suffix = ' FOR UPDATE' if lock else ''
        cursor.execute(
            "SELECT * FROM conversations WHERE id=%s AND "
            "(channel='web' OR chat_id IS NULL OR (chat_id=%s AND %s::text IS NOT NULL))" + suffix,
            (conversation_id, owner_chat_id, owner_chat_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ConversationNotFound(conversation_id)
        return row

    def create_question(self, text, *, document_id=None, conversation_id=None, owner_chat_id=None):
        text = text.strip()
        if not text:
            raise ValueError('question is empty')
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            attachments = None
            if document_id is not None:
                cur.execute('SELECT detail_document FROM document_projection WHERE id=%s', (document_id,))
                document = cur.fetchone()
                if document is None:
                    raise DocumentNotFound(document_id)
                title = document['detail_document'].get('title') or ''
                attachments = [{'kind': 'doc', 'ref': str(document_id), 'label': title}]
            if conversation_id is None:
                state = json.dumps({'attached_doc_ids': [document_id]} if document_id is not None else {}, ensure_ascii=False)
                cur.execute("INSERT INTO conversations (title, channel, state_json) VALUES (%s, 'web', %s) RETURNING id",
                            (text[:60], state))
                conversation_id = cur.fetchone()['id']
            else:
                self._owned(cur, conversation_id, owner_chat_id, lock=True)
                if document_id is not None:
                    raise ValueError('attaching a document to an existing conversation is not implemented')
                cur.execute("UPDATE conversations SET updated_at=to_char(timezone('utc', now()), 'YYYY-MM-DD HH24:MI:SS') WHERE id=%s", (conversation_id,))
            cur.execute("INSERT INTO chat_messages (conversation_id, role, content, attachments_json) VALUES (%s, 'user', %s, %s) RETURNING id",
                        (conversation_id, text, json.dumps(attachments, ensure_ascii=False) if attachments else None))
            return conversation_id, cur.fetchone()['id']

    def append_assistant(self, conversation_id, content, *, owner_chat_id=None, model=None, citations=None, gaps=None, route=None):
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            self._owned(cur, conversation_id, owner_chat_id, lock=True)
            encode = lambda value: json.dumps(value, ensure_ascii=False) if value else None
            cur.execute("INSERT INTO chat_messages (conversation_id, role, content, citations_json, gaps_json, model, route_json) VALUES (%s, 'assistant', %s, %s, %s, %s, %s) RETURNING id",
                        (conversation_id, content, encode(citations), encode(gaps), model, encode(route)))
            message_id = cur.fetchone()['id']
            cur.execute("UPDATE conversations SET updated_at=to_char(timezone('utc', now()), 'YYYY-MM-DD HH24:MI:SS') WHERE id=%s", (conversation_id,))
            return message_id

    def detail(self, conversation_id, *, owner_chat_id=None):
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            conversation = self._owned(cur, conversation_id, owner_chat_id)
            cur.execute('SELECT * FROM chat_messages WHERE conversation_id=%s ORDER BY id', (conversation_id,))
            return conversation, cur.fetchall()

    def list(self, *, owner_chat_id=None, limit=20):
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at, "
                        "(SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) AS message_count "
                        "FROM conversations c WHERE c.channel='web' OR c.chat_id IS NULL "
                        "OR (c.chat_id=%s AND %s::text IS NOT NULL) ORDER BY c.updated_at DESC, c.id DESC LIMIT %s",
                        (owner_chat_id, owner_chat_id, max(1, min(limit, 100))))
            return cur.fetchall()

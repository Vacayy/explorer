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


class TargetNotFound(LookupError):
    pass


class ConversationImportConflict(RuntimeError):
    pass


def import_sqlite_conversations(source, target):
    """Import an immutable SQLite snapshot into empty PG tables atomically.

    IDs and JSON text are kept unchanged. Existing target rows or references
    missing only from PG stop the import. Already-missing source documents are
    recorded explicitly and remain unchanged in the conversation data.
    The caller owns both connections and selects the isolated PG schema.
    """
    conversations = [tuple(r) for r in source.execute(
        'SELECT id,title,anchor_entity_id,channel,chat_id,summary,state_json,created_at,updated_at FROM conversations ORDER BY id')]
    messages = [tuple(r) for r in source.execute(
        'SELECT id,conversation_id,role,content,citations_json,gaps_json,model,route_json,attachments_json,created_at FROM chat_messages ORDER BY id')]
    links = [tuple(r) for r in source.execute(
        'SELECT message_id,entity_id,link_type FROM chat_entity_links ORDER BY message_id,entity_id')]

    conversation_ids = {r[0] for r in conversations}
    message_ids = {r[0] for r in messages}
    if any(r[1] not in conversation_ids for r in messages) or any(r[0] not in message_ids for r in links):
        raise ConversationImportConflict('orphan conversation or message reference')
    entity_ids = {r[2] for r in conversations if r[2] is not None} | {r[1] for r in links}
    document_ids = set()
    try:
        for row in conversations:
            state = json.loads(row[6] or '{}')
            document_ids.update(int(i) for i in state.get('attached_doc_ids', []))
            for ref in state.get('attached_refs', []):
                if ref.get('kind') == 'doc':
                    document_ids.add(int(ref['ref']))
        for row in messages:
            for item in json.loads(row[4] or '[]'):
                if item.get('doc_id') is not None:
                    document_ids.add(int(item['doc_id']))
            for item in json.loads(row[8] or '[]'):
                if item.get('kind') == 'doc':
                    document_ids.add(int(item['ref']))
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ConversationImportConflict('invalid document reference in source') from exc

    with target.transaction():
        target.execute('LOCK TABLE conversations, chat_messages, chat_entity_links, conversation_import_unresolved_docs, conversation_import_origin IN ACCESS EXCLUSIVE MODE')
        if any(target.execute('SELECT EXISTS(SELECT 1 FROM ' + table + ')').fetchone()[0]
               for table in ('conversations', 'chat_messages', 'chat_entity_links', 'conversation_import_unresolved_docs', 'conversation_import_origin')):
            raise ConversationImportConflict('target is not empty; refusing to overwrite')
        unresolved_source = set()
        if document_ids:
            pg_docs = {r[0]: r[1] for r in target.execute(
                'SELECT id,detail_document FROM document_projection WHERE id = ANY(%s)', (list(document_ids),))}
            source_docs = {}
            ids = sorted(document_ids)
            for start in range(0, len(ids), 400):
                batch = ids[start:start + 400]
                placeholders = ','.join('?' for _ in batch)
                for row in source.execute(
                    f'SELECT id,source_type,url,title,published_at FROM raw_documents WHERE id IN ({placeholders})', tuple(batch)):
                    source_docs[row[0]] = tuple(row[1:])
            unresolved_source = document_ids - source_docs.keys()
            missing_in_pg = source_docs.keys() - pg_docs.keys()
            if missing_in_pg:
                raise ConversationImportConflict(f'{len(missing_in_pg)} source documents are missing from PG')
            fields = ('source_type', 'url', 'title', 'published_at')
            mismatched = sum(any(value != pg_docs[doc_id].get(key) for key, value in zip(fields, values))
                             for doc_id, values in source_docs.items())
            if mismatched:
                raise ConversationImportConflict(f'{mismatched} document identities differ')
        if entity_ids:
            found = {int(r[0]) for r in target.execute(
                "SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='entities' AND row_data->>'id' = ANY(%s)",
                ([str(i) for i in entity_ids],))}
            if found != entity_ids:
                raise ConversationImportConflict(f'{len(entity_ids - found)} entity references are missing')
        with target.cursor() as cur:
            cur.executemany('INSERT INTO conversations (id,title,anchor_entity_id,channel,chat_id,summary,state_json,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', conversations)
            cur.executemany('INSERT INTO chat_messages (id,conversation_id,role,content,citations_json,gaps_json,model,route_json,attachments_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', messages)
            cur.executemany('INSERT INTO chat_entity_links (message_id,entity_id,link_type) VALUES (%s,%s,%s)', links)
            cur.executemany("INSERT INTO conversation_import_unresolved_docs (document_id,reason) VALUES (%s,'missing_in_source')",
                            [(i,) for i in sorted(unresolved_source)])
            cur.executemany('INSERT INTO conversation_import_origin (conversation_id) VALUES (%s)', [(r[0],) for r in conversations])
        # SQLite AUTOINCREMENT remembers deleted IDs in sqlite_sequence.
        # Preserve that high-water mark rather than reusing deleted chat IDs.
        has_sequence = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
        for table in ('conversations', 'chat_messages'):
            prior = source.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone() if has_sequence else None
            high_water = int(prior[0]) if prior and prior[0] is not None else 0
            target.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST(COALESCE((SELECT max(id) FROM " + table + "),0),%s,1), (GREATEST(COALESCE((SELECT max(id) FROM " + table + "),0),%s)>0))", (table,high_water,high_water))
    return {'conversations': len(conversations), 'messages': len(messages), 'entity_links': len(links),
            'document_references': len(document_ids), 'entity_references': len(entity_ids),
            'documents_missing_in_source': len(unresolved_source)}


class PostgreSQLConversations:
    def __init__(self, connect):
        self.connect = connect

    def search_document_targets(self, query, *, limit):
        """Search the same immutable document projection used by the chat."""
        from pipeline.chat_targets import SOURCE_LABEL
        with self.connect() as conn:
            from pipeline.postgres_graph_fixture import _guard
            _guard(conn)
            rows = conn.execute("""SELECT id,detail_document FROM document_projection
                WHERE feed_visible AND COALESCE(detail_document->>'title','') <> ''
                  AND strpos(lower(detail_document->>'title'), lower(%s)) > 0
                ORDER BY detail_document->>'published_at' DESC NULLS LAST,id DESC LIMIT %s""",
                (query, limit)).fetchall()
        return [{'kind': 'doc', 'ref': str(ident), 'label': doc.get('title', '')[:200],
                 'sub': SOURCE_LABEL.get(doc.get('source_type'), doc.get('source_type')),
                 'date': (doc.get('published_at') or '')[:10] or None}
                for ident, doc in rows]

    @staticmethod
    def _check_market_generation(conn):
        row = conn.execute('SELECT m.linked_document_generation,m.generation_id=s.generation_id '
                           'FROM sector_market_metadata m CROSS JOIN snapshot_metadata s '
                           'WHERE m.singleton AND s.singleton').fetchone()
        if row != (True, True):
            raise ValueError('Market snapshot does not match document generation')

    def search_stock_targets(self, query, *, limit):
        from pipeline.chat_targets import stock_rank
        if not query:
            return []
        with self.connect() as conn:
            self._check_market_generation(conn)
            rows = conn.execute("""SELECT c.stock_code,c.corp_name,p.trade_date,p.close,p.market_cap
                FROM sector_market_companies c LEFT JOIN LATERAL (
                  SELECT trade_date,close,market_cap FROM sector_market_prices
                  WHERE stock_code=c.stock_code AND close IS NOT NULL ORDER BY trade_date DESC LIMIT 1
                ) p ON TRUE WHERE strpos(lower(COALESCE(c.corp_name,'')),lower(%s))>0
                    OR strpos(c.stock_code,%s)>0""", (query, query)).fetchall()
        rows.sort(key=lambda r: (stock_rank(r[1] or '', r[0], query), -(r[4] or 0), r[1] or ''))
        return [{'kind': 'stock', 'ref': code, 'label': name or code, 'code': code,
                 'sub': code, 'date': day} for code, name, day, _, _ in rows[:limit]]

    @classmethod
    def stock_label(cls, conn, code):
        cls._check_market_generation(conn)
        row = conn.execute('SELECT corp_name FROM sector_market_companies WHERE stock_code=%s', (code,)).fetchone()
        return (row[0] or code) if row else None

    def search_person_targets(self, query, *, limit):
        if not query:
            return []
        with self.connect() as conn:
            rows = conn.execute("SELECT row_data->>'id',row_data->>'name' FROM legacy_snapshot_rows "
                "WHERE table_name='entities' AND row_data->>'type'='person' "
                "AND row_data->>'status'='active' AND strpos(lower(row_data->>'name'),lower(%s))>0 "
                "ORDER BY (lower(row_data->>'name')=lower(%s)) DESC,row_data->>'name' LIMIT %s",
                (query, query, limit)).fetchall()
        return [{'kind': 'person', 'ref': ident, 'label': name, 'sub': '인물'} for ident, name in rows]

    @staticmethod
    def person_label(conn, ident):
        row = conn.execute("SELECT row_data->>'name' FROM legacy_snapshot_rows WHERE table_name='entities' "
            "AND row_data->>'id'=%s AND row_data->>'type'='person' AND row_data->>'status'='active' LIMIT 1",
            (str(ident),)).fetchone()
        return row[0] if row else None

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

    def create_question_with_refs(self, text, *, refs=None, conversation_id=None, owner_chat_id=None,
                                  max_new=5):
        """Atomically save a question and its full selected document list."""
        from pipeline.chat_targets import merge_refs
        text = text.strip()
        if not text:
            raise ValueError('question is empty')
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            state = {}
            if conversation_id is not None:
                row = self._owned(cur, conversation_id, owner_chat_id, lock=True)
                state = json.loads(row['state_json'] or '{}')
            previous = [r for r in state.get('attached_refs', []) if isinstance(r, dict)]
            previous += [{'kind': 'doc', 'ref': str(i), 'label': ''} for i in state.get('attached_doc_ids', [])
                         if not any(r.get('kind') == 'doc' and str(r.get('ref')) == str(i) for r in previous)]
            if refs is not None:
                if any(r.get('kind') not in ('doc', 'stock', 'person') for r in previous + refs):
                    raise ValueError('target type is not supported in the fixture')
                selected, added = merge_refs(previous, refs, max_new=max_new)
                for ref in added:
                    if ref['kind'] == 'person':
                        label = self.person_label(conn, ref['ref'])
                        if not label:
                            raise TargetNotFound(ref['ref'])
                        ref['label'] = label
                        continue
                    if ref['kind'] == 'stock':
                        label = self.stock_label(conn, ref['ref'])
                        if not label:
                            raise TargetNotFound(ref['ref'])
                        ref['label'] = label
                        continue
                    try:
                        ident = int(ref['ref'])
                    except ValueError as exc:
                        raise DocumentNotFound(ref['ref']) from exc
                    cur.execute('SELECT detail_document FROM document_projection WHERE id=%s', (ident,))
                    document = cur.fetchone()
                    if not document:
                        raise DocumentNotFound(ident)
                    if conversation_id is not None:
                        cur.execute('SELECT EXISTS(SELECT 1 FROM conversation_import_origin WHERE conversation_id=%s) '
                                    'AND EXISTS(SELECT 1 FROM conversation_import_unresolved_docs WHERE document_id=%s) AS unresolved',
                                    (conversation_id, ident))
                        if cur.fetchone()['unresolved']:
                            raise DocumentNotFound(ident)
                    ref['label'] = ref['label'] or document['detail_document'].get('title') or str(ident)
                state['attached_refs'] = selected
                state['attached_doc_ids'] = [int(r['ref']) for r in selected if r['kind'] == 'doc']
                attachments = selected or None
            else:
                attachments = None
            encoded = json.dumps(state, ensure_ascii=False)
            if conversation_id is None:
                cur.execute("INSERT INTO conversations (title,channel,state_json) VALUES (%s,'web',%s) RETURNING id",
                            (text[:60], encoded))
                conversation_id = cur.fetchone()['id']
            else:
                cur.execute("UPDATE conversations SET state_json=%s,updated_at=to_char(timezone('utc', now()), 'YYYY-MM-DD HH24:MI:SS') WHERE id=%s",
                            (encoded, conversation_id))
            cur.execute("INSERT INTO chat_messages (conversation_id,role,content,attachments_json) VALUES (%s,'user',%s,%s) RETURNING id",
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

    def document_reference_status(self, conversation_id, document_id, *, owner_chat_id=None):
        """Never resolve an imported dangling ID to a later, unrelated document."""
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            self._owned(cur, conversation_id, owner_chat_id)
            cur.execute('SELECT EXISTS(SELECT 1 FROM conversation_import_origin WHERE conversation_id=%s) '
                        'AND EXISTS(SELECT 1 FROM conversation_import_unresolved_docs WHERE document_id=%s) AS unresolved',
                        (conversation_id, document_id))
            if cur.fetchone()['unresolved']:
                return {'available': False, 'reason': 'missing_in_source'}
            cur.execute('SELECT detail_document FROM document_projection WHERE id=%s', (document_id,))
            row = cur.fetchone()
            return {'available': row is not None, 'reason': None if row else 'not_found',
                    'document': row['detail_document'] if row else None}

    def load_context(self, conversation_id, question, *, owner_chat_id=None):
        """Match existing recent-message and same-owner related-note semantics."""
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            conversation = self._owned(cur, conversation_id, owner_chat_id)
            try:
                state = json.loads(conversation['state_json'] or '{}')
            except (ValueError, TypeError):
                state = {}
            cur.execute('SELECT id,role,content FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 5',
                        (conversation_id,))
            recent = list(reversed(cur.fetchall()))
            if recent and recent[-1]['role'] == 'user' and recent[-1]['content'] == question:
                recent.pop()
            entity_ids = [e['id'] for e in state.get('entities', []) if isinstance(e, dict) and e.get('id')]
            related = []
            if entity_ids:
                cur.execute('SELECT DISTINCT c.id,c.title,c.summary,c.updated_at FROM conversations c '
                            'LEFT JOIN chat_messages m ON m.conversation_id=c.id '
                            'LEFT JOIN chat_entity_links l ON l.message_id=m.id '
                            'WHERE c.id<>%s AND c.summary IS NOT NULL AND c.chat_id IS NOT DISTINCT FROM %s '
                            'AND (c.anchor_entity_id=ANY(%s) OR l.entity_id=ANY(%s)) '
                            'ORDER BY c.updated_at DESC LIMIT 2',
                            (conversation_id, conversation['chat_id'], entity_ids, entity_ids))
                related = [{'id': r['id'], 'title': r['title'], 'note': r['summary'], 'updated_at': r['updated_at']}
                           for r in cur.fetchall()]
            return {'note': conversation['summary'], 'state': state, 'recent': recent[-4:], 'related': related}

    def update_state(self, conversation_id, *, entities, intent, tools, doc_ids, last_citations=None, owner_chat_id=None):
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            conversation = self._owned(cur, conversation_id, owner_chat_id, lock=True)
            try:
                state = json.loads(conversation['state_json'] or '{}')
            except (ValueError, TypeError):
                state = {}
            merged = {e['name']: e for e in state.get('entities', []) if e.get('name')}
            for entity in entities:
                if entity.get('name'):
                    merged[entity['name']] = entity
            state.update({'entities': list(merged.values())[-8:], 'last_intent': intent, 'last_tools': tools,
                          'doc_ids': (doc_ids + [d for d in state.get('doc_ids', []) if d not in doc_ids])[:10],
                          'last_citations': (last_citations or [])[:10]})
            cur.execute('UPDATE conversations SET state_json=%s WHERE id=%s',
                        (json.dumps(state, ensure_ascii=False), conversation_id))

    def record_model_call(self, job, model, engine, effort, result, duration_ms, error):
        """Record model usage in the same PG store without saving prompts."""
        from pipeline.ops import mask_secrets
        usage = (result.usage if result else {}) or {}
        safe_error = mask_secrets(str(error))[:500] if error is not None else None
        with self.connect() as conn:
            conn.execute('INSERT INTO chat_model_calls '
                         '(job,model,engine,effort,input_tokens,cache_create_tokens,cache_read_tokens,'
                         'output_tokens,thinking_tokens,cost_usd,duration_ms,ok,error) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (job or None, model, engine, effort, usage.get('input'), usage.get('cache_create'),
                          usage.get('cache_read'), usage.get('output'), usage.get('thinking'),
                          result.cost_usd if result else None, duration_ms, error is None, safe_error))

    def list(self, *, owner_chat_id=None, limit=20, stock=None):
        owner = "(c.channel='web' OR c.chat_id IS NULL OR (c.chat_id=%s AND %s::text IS NOT NULL))"
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            if stock:
                # The legacy rule: conversations anchored to the company, or whose messages link it.
                company = conn.execute("SELECT (row_data->>'id')::bigint FROM legacy_snapshot_rows WHERE table_name='entities' "
                                       "AND row_data->>'type'='company' AND row_data->>'aliases'=%s "
                                       "ORDER BY (row_data->>'id')::bigint LIMIT 1", (stock,)).fetchone()
                cur.execute("SELECT DISTINCT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at, "
                            "(SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) AS message_count "
                            "FROM conversations c LEFT JOIN chat_messages m ON m.conversation_id=c.id "
                            "LEFT JOIN chat_entity_links cel ON cel.message_id=m.id "
                            f"WHERE (c.anchor_entity_id=%s OR cel.entity_id=%s) AND {owner} "
                            "ORDER BY c.updated_at DESC LIMIT %s",
                            (company and company[0], company and company[0], owner_chat_id, owner_chat_id, max(1, min(limit, 100))))
                return cur.fetchall()
            cur.execute("SELECT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at, "
                        "(SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) AS message_count "
                        f"FROM conversations c WHERE {owner} ORDER BY c.updated_at DESC, c.id DESC LIMIT %s",
                        (owner_chat_id, owner_chat_id, max(1, min(limit, 100))))
            return cur.fetchall()

    def rename(self, conversation_id, title, *, owner_chat_id=None):
        """The legacy title edit (D-145); returns the list row."""
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            self._owned(cur, conversation_id, owner_chat_id, lock=True)
            cur.execute('UPDATE conversations SET title=%s WHERE id=%s', (title, conversation_id))
            cur.execute("SELECT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at, "
                        "(SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) AS message_count "
                        'FROM conversations c WHERE c.id=%s', (conversation_id,))
            return cur.fetchone()

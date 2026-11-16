"""Isolated PostgreSQL chat generation; no live service is configured here."""
from pipeline import chat
from pipeline.postgres_chat_runtime import PostgreSQLChatRuntime


def generate_answer(store, tools, conversation_id, question, *, owner_chat_id=None,
                    quote=None, page_context=None):
    """Complete a previously stored question, keeping conversation data in PG."""
    stream = chat._open(conversation_id)
    runtime = PostgreSQLChatRuntime(store, conversation_id, tools, owner_chat_id=owner_chat_id)
    try:
        context = store.load_context(conversation_id, question, owner_chat_id=owner_chat_id)
        turn = chat.run_turn(question, conversation_id=conversation_id, ctx=context, runtime=runtime,
                             on_text=stream.push, on_status=stream.set_status,
                             quote=quote, page_context=page_context)
        answer = turn.answer or chat._no_evidence_text(turn)
        store.append_assistant(conversation_id, answer, owner_chat_id=owner_chat_id,
                               citations=turn.citations or None, gaps=turn.gaps or None,
                               model=turn.model, route=turn.route_log())
        # An answer is already durable even if optional memory maintenance fails.
        try:
            entities = []
            for entity in turn.route.get('entities') or []:
                if isinstance(entity, dict) and entity.get('name'):
                    eid, _, _ = tools.chunk_rag.entity_scope(entity['name'])
                    entities.append({'name': entity['name'], 'kind': entity.get('kind'), 'id': eid})
            store.update_state(conversation_id, owner_chat_id=owner_chat_id, entities=entities,
                               intent=turn.route.get('intent'), tools=[c['name'] for c in turn.calls],
                               doc_ids=[c['doc_id'] for c in turn.citations if c.get('doc_id')],
                               last_citations=[{'n': c['n'], 'kind': c.get('kind'), 'doc_id': c.get('doc_id'),
                                                'title': c['title']} for c in turn.citations])
        except Exception:
            pass
        return {'answer': answer, 'citations': turn.citations, 'gaps': turn.gaps, 'model': turn.model}
    except Exception:
        # Do not expose model errors or connection details in a conversation.
        message = '답변 생성에 실패했습니다. 다시 질문해주세요.'
        store.append_assistant(conversation_id, message, owner_chat_id=owner_chat_id)
        return {'answer': None, 'citations': [], 'gaps': [], 'model': None, 'error': message}
    finally:
        stream.finish()

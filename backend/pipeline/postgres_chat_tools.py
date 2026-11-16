"""Experimental PG document tools for the isolated chat runtime.

This currently supports document opening and basic search only. Other tools and
filters fail explicitly; it is not a replacement for the full SQLite chat API.
"""
from pipeline.chat_tools import ToolResult
from models.spine import FeedDocument
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_search_feed import search_feed


class UnsupportedPostgresChatTool(NotImplementedError):
    pass


class PostgreSQLChatTools:
    def __init__(self, connect, index, *, query_vector=None, allow_lexical_only=False, chunk_rag=None):
        if query_vector is None and not allow_lexical_only and chunk_rag is None:
            raise ValueError('query embedding provider or explicit lexical-only mode required')
        self.connect = connect
        self.index = index
        self.query_vector = query_vector
        self.chunk_rag = chunk_rag
        self.reader = PostgreSQLDocumentReader(connect)

    def gather_attached_refs(self, refs):
        raise UnsupportedPostgresChatTool('non-document attached targets are not implemented')

    @staticmethod
    def _item(doc):
        return {'kind': 'doc', 'doc_id': doc.id, 'title': doc.title,
                'text': (doc.content or '')[:4000], 'date': (doc.published_at or '')[:10],
                'href': f'/doc/{doc.id}', 'source_type': doc.source_type}

    def run_tool(self, call):
        name = call.get('name')
        args = call.get('args') or {}
        if name == 'open_doc':
            doc = self.reader.get(int(args['doc_id']))
            return ToolResult(name, args, [self._item(doc)] if doc else [], None if doc else '문서 없음')
        if name != 'search_docs':
            raise UnsupportedPostgresChatTool(f'{name} is not implemented in the PG fixture')
        if (args.get('entity') or args.get('channel')) and self.chunk_rag is None:
            raise UnsupportedPostgresChatTool('requested filter is not implemented in the PG fixture')
        query = (args.get('query') or '').strip()
        if not query:
            raise ValueError('search query is empty')
        variants = args.get('variants') or []
        if isinstance(variants, str):
            variants = [variants]
        variants = [v for v in variants if isinstance(v, str) and v.strip()][:3]
        queries = [query] + [q.strip() for q in variants[:3] if isinstance(q, str) and q.strip()]
        limit = max(1, min(int(args.get('k', 12)), 20))
        if self.chunk_rag is not None:
            from pipeline.rag import retrieve_docs
            scope = self.chunk_rag.channel_scope(args['channel']) if args.get('channel') else None
            if args.get('channel') and scope is None:
                return ToolResult(name, args, [], f"'{args['channel']}' 채널·블로거를 구독 소스에서 찾지 못함")
            eid, terms, assumptions = (self.chunk_rag.entity_scope(args['entity'])
                                       if args.get('entity') else (None, None, {}))
            docs = retrieve_docs(query, k=limit, since_days=args.get('since_days'), source=args.get('source'),
                                 variants=variants or None, doc_ids=scope[0] if scope else None,
                                 entity_id=eid, entity_terms=terms, runtime=self.chunk_rag)
            note = '실험용 PG 청크 검색; 출처명 및 출처별 부분일치 폴백 미구현'
            if not docs and scope and scope[0]:
                docs = sorted(self.chunk_rag.fetch_docs(list(scope[0])),
                              key=lambda d: d.get('published_at') or '', reverse=True)[:limit]
                note = '의미 검색에 걸린 대목이 없어 이 채널의 최근 글을 최신순으로 돌려줌'
            items = [{'kind': 'doc', 'doc_id': d['id'], 'title': d['title'], 'text': d['excerpt'],
                      'date': (d['published_at'] or '')[:10], 'href': f"/doc/{d['id']}",
                      'source_type': d['source_type']} for d in docs]
            if scope:
                note += f" ('{args['channel']}' → {', '.join(dict.fromkeys(scope[1]))} 범위 검색) · {scope[2]}"
            if assumptions.get('ambiguous'):
                note += ' · ' + assumptions['ambiguous']
            return ToolResult(name, args, items, note, assumed=assumptions.get('assumed', []))
        found = []
        seen = set()
        items = []
        with self.connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for q in queries:
                vector = self.query_vector(q) if self.query_vector else None
                result = search_feed(conn, self.index, q, vector=vector, source=args.get('source'),
                                     days=args.get('since_days'), size=limit)
                for doc in result.items:
                    if doc.id not in seen:
                        seen.add(doc.id)
                        found.append(doc.id)
            if found:
                rows = conn.execute('SELECT id,detail_document FROM document_projection WHERE id=ANY(%s)',
                                    (found[:limit],)).fetchall()
                docs = {row[0]: FeedDocument.model_validate(row[1]) for row in rows}
                items = [self._item(docs[doc_id]) for doc_id in found[:limit] if doc_id in docs]
        note = '실험용 PG 문서 검색' + (' (키워드만)' if self.query_vector is None else ' (키워드·벡터)')
        return ToolResult(name, args, items, note)

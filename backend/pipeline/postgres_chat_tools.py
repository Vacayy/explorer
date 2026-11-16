"""Experimental PG document tools for the isolated chat runtime.

Document opening, search, narratives, causal graphs, prices and earnings calls are experimental.
Other tools fail explicitly; this is not a replacement for the full chat API.
"""
from pipeline.chat_tools import ToolResult
from models.spine import FeedDocument
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_search_feed import search_feed


class UnsupportedPostgresChatTool(NotImplementedError):
    pass


class PostgreSQLChatTools:
    def __init__(self, connect, index, *, query_vector=None, allow_lexical_only=False, chunk_rag=None, entity_resolver=None,
                 portfolio_provider=None, evidence_search=None):
        if query_vector is None and not allow_lexical_only and chunk_rag is None:
            raise ValueError('query embedding provider or explicit lexical-only mode required')
        self.connect = connect
        self.index = index
        self.query_vector = query_vector
        self.chunk_rag = chunk_rag
        self.entity_resolver = entity_resolver
        self.portfolio_provider = portfolio_provider
        # evidence_search(args) -> ToolResult | None: the legacy chunk search run elsewhere (compute worker);
        # None falls back to the document index search below.
        self.evidence_search = evidence_search
        self.reader = PostgreSQLDocumentReader(connect)

    def gather_attached_refs(self, refs):
        from pipeline.postgres_conversations import PostgreSQLConversations
        items, empty = [], []
        with self.connect() as conn:
            for ref in refs:
                if ref.get('kind') == 'doc':
                    continue
                if ref.get('kind') == 'person':
                    continue
                if ref.get('kind') != 'stock':
                    raise UnsupportedPostgresChatTool('target type is not implemented')
                code = str(ref['ref'])
                label = PostgreSQLConversations.stock_label(conn, code)
                row = conn.execute('SELECT trade_date,close FROM sector_market_prices '
                    'WHERE stock_code=%s AND close IS NOT NULL ORDER BY trade_date DESC LIMIT 1', (code,)).fetchone()
                if not label or not row:
                    empty.append('국내 종목 ' + (label or code))
                    continue
                items.append({'kind': 'quote', 'title': f'{label}({code}) 저장 시세',
                    'text': f'{row[0]} 기준 저장 종가 {row[1]:,}원. 실시간 시세가 아닙니다. 재무·공시 자료는 이 항목에 포함되지 않습니다.',
                    'date': row[0], 'doc_id': None, 'href': f'/analyze/{code}/summary', 'tool': 'attached_targets'})
        for ref in refs:
            if ref.get('kind') != 'person':
                continue
            with self.connect() as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                ident = str(ref['ref'])
                label = PostgreSQLConversations.person_label(conn, ident)
                if not label or not ident.isdigit():
                    empty.append('인물 ' + (label or ident))
                    continue
                vector = self.query_vector(label) if self.query_vector else None
                result = search_feed(conn, self.index, label, vector=vector, size=3, entity_id=int(ident))
                if not result.items:
                    empty.append('인물 ' + label)
                for doc in result.items:
                    item = self._item(doc)
                    item['tool'] = 'attached_targets'
                    items.append(item)
        return items[:12], empty

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
        if name == 'get_portfolio':
            if self.portfolio_provider is None:
                raise UnsupportedPostgresChatTool('explicit portfolio owner provider is required')
            return self.portfolio_provider()
        if name == 'get_transcripts':
            import sqlite3
            from pipeline.chat_tools import get_transcripts
            from pipeline.postgres_urgent_selection_fixture import open_snapshot
            with self.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                if self.chunk_rag is not None:
                    self.chunk_rag._check(pg)
                db, uri, _ = open_snapshot(pg, ('transcript_follow', 'transcripts'))
                try:
                    def connect():
                        conn = sqlite3.connect(uri, uri=True)
                        conn.row_factory = sqlite3.Row
                        return conn

                    def resolve_entity(name):
                        if self.chunk_rag is None:
                            raise UnsupportedPostgresChatTool('entity resolver is required for this company name')
                        ident, _, _ = self.chunk_rag.entity_scope(name, prefer=('company',))
                        return {'id': ident} if ident else None

                    result = get_transcripts(args['companies'], args.get('n_per', 1),
                                             connection_factory=connect, entity_resolver=resolve_entity)
                    if self.chunk_rag is not None:
                        self.chunk_rag._check(pg)
                    return result
                finally:
                    db.close()
        if name == 'get_narrative':
            from pipeline.chat_tools import get_narrative
            from pipeline.postgres_narrative_fixture import cached_narrative
            if self.chunk_rag is None:
                raise UnsupportedPostgresChatTool('entity resolver is required for narratives')
            with self.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.chunk_rag._check(pg)
                def cache_lookup(topic):
                    return cached_narrative(pg, topic).model_dump()

                def entity_lookup(topic):
                    ident, terms, _ = self.chunk_rag.entity_scope(topic, prefer=('theme', 'sector'))
                    return terms[0] if ident and terms else None

                result = get_narrative(args['topic'], cache_lookup=cache_lookup, entity_lookup=entity_lookup)
                self.chunk_rag._check(pg)
                return result
        if name == 'get_worldmodel':
            import sqlite3
            from pipeline.chat_tools import get_worldmodel
            from pipeline.postgres_urgent_selection_fixture import open_snapshot
            if self.chunk_rag is None:
                raise UnsupportedPostgresChatTool('entity resolver is required for causal graphs')
            with self.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.chunk_rag._check(pg)
                db, uri, _ = open_snapshot(pg, ('entities', 'entity_relations', 'narratives'))
                try:
                    def connect():
                        conn = sqlite3.connect(uri, uri=True)
                        conn.row_factory = sqlite3.Row
                        return conn

                    def resolve_entity(name, assumptions):
                        ident, terms, found = self.chunk_rag.entity_scope(name)
                        assumptions.update(found)
                        return {'id': ident, 'name': terms[0]} if ident and terms else None

                    result = get_worldmodel(args['entity'], connection_factory=connect,
                                            entity_resolver=resolve_entity)
                    self.chunk_rag._check(pg)
                    return result
                finally:
                    db.close()
        if name == 'get_price_history':
            from pipeline.chat_tools import get_price_history
            from pipeline.postgres_chat_chunks import ChatChunkImportConflict
            from pipeline.postgres_chat_read_projection import price_history_projection
            if self.chunk_rag is None:
                raise UnsupportedPostgresChatTool('entity resolver is required for price history')
            with self.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.chunk_rag._check(pg)
                market = pg.execute('SELECT generation_id,linked_document_generation FROM sector_market_metadata WHERE singleton').fetchone()
                if not market or not market[1] or str(market[0]) != self.chunk_rag.chunks.generation:
                    raise ChatChunkImportConflict('price generation differs from documents')
                ident, terms, assumptions = self.chunk_rag.entity_scope(args['stock'], prefer=('company',))
                entity = (pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entities' "
                                     "AND row_data->>'id'=%s ORDER BY row_ordinal LIMIT 1", (str(ident),)).fetchone()
                          if ident else None)
                entity = entity[0] if entity else None
                code = entity.get('aliases') if entity and entity.get('type') == 'company' else None
                label = entity.get('name') if entity else None
                rows = (pg.execute('SELECT stock_code,trade_date,open,high,low,close,volume,fetched_at '
                                   'FROM sector_market_prices WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 61',
                                   (code,)).fetchall() if code else [])
                self.chunk_rag._check(pg)
                with price_history_projection(rows) as factory:
                    def resolve_company(_stock, asm):
                        asm.update(assumptions)
                        return code, label
                    return get_price_history(args['stock'], args.get('days', 10),
                                             connection_factory=factory, company_resolver=resolve_company)
        if name != 'search_docs':
            raise UnsupportedPostgresChatTool(f'{name} is not implemented in the PG fixture')
        if self.chunk_rag is None and self.evidence_search is not None:
            result = self.evidence_search(args)
            if result is not None:
                return result
        if (args.get('channel') or (args.get('entity') and self.entity_resolver is None)) and self.chunk_rag is None:
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
            # Keep embedding and reranking from overlapping in one worker.
            with self.chunk_rag.retrieval_lock:
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
        entity_id = None
        assumptions = {}
        if args.get('entity'):
            entity_id, _, assumptions = self.entity_resolver(args['entity'])
            if entity_id is None:
                return ToolResult(name, args, [], '대상을 확인할 수 없어 범위 검색을 수행하지 않았습니다.', assumed=assumptions.get('assumed', []))
        with self.connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for q in queries:
                vector = self.query_vector(q) if self.query_vector else None
                result = search_feed(conn, self.index, q, vector=vector, source=args.get('source'),
                                     days=args.get('since_days'), size=limit, entity_id=entity_id)
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
        excluded = getattr(self.index, 'excluded_vectors', 0)
        if excluded:
            note += f' · 오래된 벡터 {excluded}건 제외'
        return ToolResult(name, args, items, note, assumed=assumptions.get('assumed', []))

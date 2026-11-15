"""Fixture detail reader combining a preserved snapshot and the write ledger.

This does not publish a feed or alter a snapshot. Modified video documents are
intentionally rejected until the legacy digest-job bridge is implemented.
"""
from models.spine import FeedDocument
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader


class LedgerDetailFixture:
    def __init__(self, factory):
        self.factory = factory
        self.legacy = PostgreSQLRawDocumentReader(factory)

    def get(self, ident):
        with self.factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row = conn.execute('SELECT d.source_type,d.title,d.url,d.published_at,d.raw_content,d.markdown, '
                               'd.media_json,d.revision,e.summary,e.model FROM ingest_documents d '
                               'LEFT JOIN ingest_enrichments e ON e.document_id=d.id AND e.revision=d.revision '
                               'WHERE d.id=%s', (ident,)).fetchone()
            if row is None:
                return None
            source,title,url,published,raw,markdown,media,revision,summary,model = row
            original = self.legacy.get_in_transaction(conn, ident)
            if original is not None and revision == 1:
                # Unchanged documents retain all observed legacy summary/link and
                # source semantics, with separately refreshed attachment metadata.
                return original.model_copy(update={'images': media or []})
            if source == 'youtube':
                raise ValueError('Modified video details are not supported by this fixture')
            if original is None and source != 'note':
                raise ValueError('New non-note details are not supported by this fixture')
            if original is None:
                original = FeedDocument(id=ident,source_type=source,title='',url='',published_at='',
                                        summary=None,channel='내 노트',content=None,images=[],
                                        enrich_model=None,entities=[])
            # The archived links refer to the old content. Do not attach them to
            # a changed document until fresh linking is implemented.
            return original.model_copy(update={'title':title,'url':url,'published_at':published,
                'content':markdown or raw,'images':media or [],'summary':summary,'enrich_model':model,
                'entities':[]})

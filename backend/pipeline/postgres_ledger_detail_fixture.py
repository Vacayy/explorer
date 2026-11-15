"""Fixture detail reader combining a preserved snapshot and the write ledger.

This does not publish a feed or alter a snapshot. New non-note source handling
and all production routing remain outside this fixture.
"""
from models.spine import FeedDocument
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.youtube_digest import fields_from_job


class LedgerDetailFixture:
    def __init__(self, factory):
        self.factory = factory
        self.legacy = PostgreSQLRawDocumentReader(factory)

    def get(self, ident):
        with self.factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row = conn.execute('SELECT d.source_type,d.title,d.url,d.published_at,d.raw_content,d.markdown, '
                               'd.media_json,d.revision,e.summary,e.model,d.digest_status FROM ingest_documents d '
                               'LEFT JOIN ingest_enrichments e ON e.document_id=d.id AND e.revision=d.revision '
                               'WHERE d.id=%s', (ident,)).fetchone()
            if row is None:
                return None
            source,title,url,published,raw,markdown,media,revision,summary,model,digest_status = row
            original = self.legacy.get_in_transaction(conn, ident)
            if original is not None and revision == 1:
                # Unchanged documents retain all observed legacy summary/link and
                # source semantics, with separately refreshed attachment metadata.
                return original.model_copy(update={'images': media or []})
            if original is None and source != 'note':
                raise ValueError('New non-note details are not supported by this fixture')
            if original is None:
                original = FeedDocument(id=ident,source_type=source,title='',url='',published_at='',
                                        summary=None,channel='내 노트',content=None,images=[],
                                        enrich_model=None,entities=[])
            # The archived links refer to the old content. Do not attach them to
            # a changed document until fresh linking is implemented.
            video_fields = {}
            if source == 'youtube':
                job = conn.execute('SELECT transcript,status,updated_at,error FROM ingest_youtube_jobs '
                                   'WHERE document_id=%s AND revision=%s', (ident,revision)).fetchone()
                job = dict(zip(('transcript','status','updated_at','error'), job)) if job else None
                video_fields = fields_from_job({'source_type':source,'digest_status':digest_status,
                                               'markdown':markdown,'raw_content':raw}, job)
            return original.model_copy(update={'title':title,'url':url,'published_at':published,
                'content':markdown or raw,'images':media or [],'summary':summary,'enrich_model':model,
                'entities':[], **video_fields})

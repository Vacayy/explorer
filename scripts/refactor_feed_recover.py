"""Publish one validated, already-enriched feed work item without another model call.

Run only with the isolated feed hold in place and all other collector jobs stopped.
The intent and PG receipt survive a crash; an unexpected state must be reviewed.
"""
import sqlite3
import time

import refactor_collect_trial as trial
from pipeline.feed_backlog import FeedBacklog
from pipeline import feed_receipts, postgres_collected_documents_fixture


def validate(work, queue, *, receipt_exists=False):
    item = queue.next()
    if item is None:
        raise ValueError('No pending document')
    seq, connector, doc = item
    if connector != 'blog' or doc.source_type != 'blog':
        raise ValueError('Only an isolated blog recovery is supported')
    floors = trial._published_floors(work)
    rows = work.execute('SELECT id,source_type,source_id,raw_content,markdown,content_hash FROM raw_documents '
                        'WHERE source_type=? AND source_id=?', (doc.source_type, doc.source_id)).fetchall()
    if len(rows) != 1:
        raise ValueError('Expected exactly one matching work document')
    ident, source, key, raw, markdown, content_hash = rows[0]
    pending_count = work.execute('SELECT count(*) FROM raw_documents WHERE id>?', (floors['document_floor'],)).fetchone()[0]
    if not receipt_exists and (ident <= floors['document_floor'] or pending_count != 1):
        raise ValueError('Expected exactly one unpublished document')
    if receipt_exists and (pending_count not in (0, 1) or (pending_count == 1 and ident <= floors['document_floor'])):
        raise ValueError('Unexpected unpublished document after receipt')
    if (source, key) != (doc.source_type, doc.source_id) or not raw or not markdown or not content_hash:
        raise ValueError('Pending document does not match the completed work row')
    if raw != doc.raw_content:
        raise ValueError('Work content differs from the staged source document')
    enriched = work.execute('SELECT content_hash,summary FROM enrichments WHERE doc_id=?', (ident,)).fetchall()
    if len(enriched) != 1 or enriched[0][0] != content_hash or not enriched[0][1]:
        raise ValueError('A matching completed enrichment is required')
    for table, floor in (('entities', 'entity_floor'), ('entity_keywords', 'keyword_floor'),
                         ('entity_relations', 'relation_floor')):
        if work.execute(f'SELECT 1 FROM "{table}" WHERE id>? LIMIT 1', (floors[floor],)).fetchone():
            raise ValueError('Unexpected new graph row')
    return seq, doc, floors


def main():
    queue = FeedBacklog('/trial/feed-backlog.sqlite')
    work = sqlite3.connect(trial.WORK)
    work.row_factory = sqlite3.Row
    try:
        with trial._pg() as pg:
            intent = queue.intent()
            receipt_exists = bool(intent and feed_receipts.committed(pg, intent[0]))
            seq, doc, floors = validate(work, queue, receipt_exists=receipt_exists)
            if intent and intent[1] != seq:
                raise ValueError('Unexpected in-progress publication')
            token = intent[0] if intent else queue.begin_publication(seq)
            def publish():
                if pg.execute("SELECT 1 FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                              "AND row_data->>'source_type'=%s AND row_data->>'source_id'=%s LIMIT 1",
                              (doc.source_type, doc.source_id)).fetchone():
                    raise ValueError('The candidate already has this source document')
                rows = postgres_collected_documents_fixture.publish(pg, work, **floors)
                if len(rows) != 1:
                    raise ValueError('Expected exactly one published document')

            feed_receipts.publish_once(pg, token, time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()), publish)
            if not feed_receipts.committed(pg, token):
                raise RuntimeError('Publication receipt is missing')
            trial._published_floors(work, advance=True)
            work.commit()
            queue.finish_publication(token, receipt_confirmed=True)
        print('Recovered documents: 1; model calls: 0')
    finally:
        work.close()
        queue.close()


if __name__ == '__main__':
    main()

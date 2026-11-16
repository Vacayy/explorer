"""Representative collector run against the single-path candidate, with synthetic changes and no model.

Run only through `scripts/refactor_run_collector_once.sh backend/tests/integration_collected_run.py run|restore`.
`run` publishes, in one transaction: a new post linked to a new entity, an existing post re-linked to that
entity (works because new rows go first), an existing post the candidate changed meanwhile (kept, then merged)
and a deleted post (kept as unsupported). `restore` removes everything it added, by ID.
"""
import json
import os
import sqlite3
import sys

import psycopg
from psycopg.types.json import Jsonb

from pipeline import postgres_collected_changes_fixture as changes
from pipeline.postgres_collected_documents_fixture import withdraw

STATE = '/projection/integration-run.json'
WORK = '/projection/integration-work.db'
RUN = 'integration-run'

pg = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True)
pg.execute(f"SET search_path TO {os.environ['REFACTOR_FIXTURE_SCHEMA']}")


def run():
    origin = sqlite3.connect('file:/projection/current.db?mode=ro', uri=True)  # held open for the whole run
    work = sqlite3.connect(WORK)
    origin.backup(work)
    floors = {name: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for name, table in (
        ('document_floor', 'raw_documents'), ('entity_floor', 'entities'), ('keyword_floor', 'entity_keywords'),
        ('relation_floor', 'entity_relations'))}
    relinked, conflicted, deleted = [row[0] for row in pg.execute("""
        SELECT d.id FROM document_projection d JOIN document_list_projection l ON l.document_id=d.id
        WHERE d.source_type='blog' AND NOT EXISTS (SELECT 1 FROM video_projection_overrides o WHERE o.document_id=d.id)
          AND NOT EXISTS (SELECT 1 FROM document_embedding_overrides e WHERE e.document_id=d.id)
        ORDER BY l.ordinal OFFSET 70 LIMIT 3""")]
    before = changes.capture(work, floors['document_floor'])
    # The collector: a new post about a new entity, an existing post re-linked to it, one re-summarized, one deleted.
    new_doc, new_entity = floors['document_floor'] + 1, floors['entity_floor'] + 1
    columns = [c[1] for c in work.execute('PRAGMA table_info(raw_documents)')]
    template = dict(zip(columns, work.execute('SELECT * FROM raw_documents WHERE id=?', (relinked,)).fetchone()))
    template.update(id=new_doc, title='합성 신규 글 RV3', url=template['url'] + '#rv3', source_id=f"{template['source_id']}#rv3", markdown='합성 신규 본문 RV3',
                    content_hash='synthetic-rv3-new', published_at='2026-11-16T12:00:00+00:00')
    work.execute(f'INSERT INTO raw_documents ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})', list(template.values()))
    work.execute("INSERT INTO enrichments (doc_id,summary,model,content_hash) VALUES (?,?,?,?)",
                 (new_doc, '합성 신규 요약 RV3', 'synthetic', 'synthetic-rv3-new'))
    work.execute("INSERT INTO entities (id,type,name) VALUES (?,'theme','합성엔티티RV3')", (new_entity,))
    for doc in (new_doc, relinked):
        work.execute("INSERT INTO entity_links (doc_id,entity_id,link_type,confidence) VALUES (?,?,'mention',0.9)", (doc, new_entity))
    work.execute("UPDATE enrichments SET summary='합성 재요약 RV3' WHERE doc_id IN (?,?)", (relinked, conflicted))
    for table, key in (('entity_links', 'doc_id'), ('enrichments', 'doc_id'), ('raw_documents', 'id')):
        work.execute(f'DELETE FROM {table} WHERE {key}=?', (deleted,))
    work.commit()
    # Meanwhile the candidate changed another field of one of them.
    ordinal, row = pg.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                              "AND row_data->>'id'=%s", (str(conflicted),)).fetchone()
    pg.execute("INSERT INTO video_digest_overlay_rows VALUES('raw_documents',%s,%s)", (ordinal, Jsonb({**row, 'fetched_at': '2026-11-16 00:00:00'})))
    json.dump({'new_doc': new_doc, 'docs': [relinked, conflicted, deleted]}, open(STATE, 'w'))
    result = changes.publish_run(pg, work, origin, before, run_id=RUN, **floors)
    print('run', {'added': result['added'] == [new_doc], 'revised': result['revised'] == [relinked],
                  'kept': [((d == conflicted and 'conflicted') or (d == deleted and 'deleted') or d, s, r)
                           for d, s, r in result['kept']]})
    print('reprocess', {k: len(v) for k, v in changes.reprocess_conflicts(pg).items()})
    print('unprocessed', [(status, count) for status, count, _ in changes.unprocessed(pg)])
    work.close()
    origin.close()
    os.remove(WORK)


def restore():
    state = json.load(open(STATE))
    for ident in state['docs']:
        pg.execute('DELETE FROM video_projection_overrides WHERE document_id=%s', (ident,))
        pg.execute("DELETE FROM video_digest_overlay_rows WHERE (table_name='raw_documents' AND row_data->>'id'=%s) "
                   "OR (table_name IN ('enrichments','entity_links') AND row_data->>'doc_id'=%s)", (str(ident), str(ident)))
    withdraw(pg, state['new_doc'])
    print('vectors', pg.execute('DELETE FROM document_embedding_overrides WHERE document_id=ANY(%s)',
                                ([state['new_doc'], *state['docs']],)).rowcount,
          'kept rows', pg.execute('DELETE FROM collected_change_conflicts WHERE run_id=%s', (RUN,)).rowcount)
    os.remove(STATE)


{'run': run, 'restore': restore}[sys.argv[1]]()

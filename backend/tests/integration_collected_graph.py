"""Representative graph revision run (narratives/causal jobs) against the single-path candidate, no model.

Run only through `scripts/refactor_run_collector_once.sh backend/tests/integration_collected_graph.py run|restore`.
`run`: the collector changes an entity's aliases, a relation's mechanism and another relation the candidate
confirmed meanwhile (kept, then merged), and adds edge evidence. `restore` puts every touched row back by ID.
"""
import json
import os
import sqlite3
import sys

import psycopg
from psycopg.types.json import Jsonb

from pipeline import postgres_collected_changes_fixture as changes

STATE = '/projection/integration-graph.json'
WORK = '/projection/integration-graph.db'
RUN = 'integration-graph'

pg = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True)
pg.execute(f"SET search_path TO {os.environ['REFACTOR_FIXTURE_SCHEMA']}")


def visible(table, ident):
    return pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s AND row_data->>'id'=%s",
                      (table, str(ident))).fetchone()[0]


def run():
    if pg.execute("SELECT to_regclass('collected_row_revisions')").fetchone()[0] is None:
        changes.initialize_graph_revisions(pg)
    origin = sqlite3.connect('file:/projection/current.db?mode=ro', uri=True)
    work = sqlite3.connect(WORK)
    origin.backup(work)
    floors = {name: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for name, table in (
        ('document_floor', 'raw_documents'), ('entity_floor', 'entities'), ('keyword_floor', 'entity_keywords'),
        ('relation_floor', 'entity_relations'))}
    entity = work.execute("SELECT id FROM entities WHERE type='theme' ORDER BY id LIMIT 1 OFFSET 40").fetchone()[0]
    changed, confirmed = [row[0] for row in work.execute(
        'SELECT id FROM entity_relations WHERE mechanism IS NOT NULL ORDER BY id LIMIT 2 OFFSET 100')]
    narrative = work.execute('SELECT id FROM narratives ORDER BY id LIMIT 1').fetchone()[0]
    originals = {'entities': {entity: visible('entities', entity)},
                 'entity_relations': {ident: visible('entity_relations', ident) for ident in (changed, confirmed)}}
    before = changes.capture(work, floors['document_floor'])
    graph = changes.capture_graph(work)
    # The collector: new alias, rewritten mechanisms, one new piece of edge evidence.
    work.execute("UPDATE entities SET aliases=COALESCE(aliases,'')||',합성별칭RV4' WHERE id=?", (entity,))
    work.execute("UPDATE entity_relations SET mechanism='합성 메커니즘 RV4' WHERE id IN (?,?)", (changed, confirmed))
    columns = [c[1] for c in work.execute('PRAGMA table_info(narrative_edge_evidence)')]
    template = dict(zip(columns, work.execute('SELECT * FROM narrative_edge_evidence ORDER BY id LIMIT 1').fetchone()))
    evidence = work.execute('SELECT max(id)+1 FROM narrative_edge_evidence').fetchone()[0]
    template.update(id=evidence, entity_relation_id=changed, narrative_id=narrative)
    work.execute(f'INSERT INTO narrative_edge_evidence ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                 list(template.values()))
    work.commit()
    # Meanwhile the candidate confirmed the other relation by observation (a different field).
    row = {**originals['entity_relations'][confirmed], 'obs_confirmed_at': '2026-11-16 00:00:00', 'obs_confirmed_qid': -1}
    pg.execute("UPDATE question_graph_overlay_rows SET row_data=%s WHERE table_name='entity_relations' AND row_data->>'id'=%s",
               (Jsonb(row), str(confirmed)))
    pg.execute('UPDATE question_graph_overlay_relations SET source_row=%s WHERE id=%s', (Jsonb(row), confirmed))
    json.dump({'entity': entity, 'relations': [changed, confirmed], 'evidence': evidence,
               'originals': {t: {str(k): v for k, v in rows.items()} for t, rows in originals.items()}}, open(STATE, 'w'))
    result = changes.publish_run(pg, work, origin, before, run_id=RUN, graph=graph, **floors)
    print('graph', {'applied': sorted(t for t, _ in result['graph']['applied']), 'kept': result['graph']['kept'] == [('entity_relations', confirmed)],
                    'evidence_added': result['graph']['evidence_added'] == [evidence]})
    print('reprocess', {k: len(v) for k, v in changes.reprocess_conflicts(pg).items()})
    print('entity aliases', '합성별칭RV4' in (visible('entities', entity).get('aliases') or ''))
    merged = visible('entity_relations', confirmed)
    print('merged relation', merged['mechanism'] == '합성 메커니즘 RV4', merged.get('obs_confirmed_qid') == -1,
          'changed relation', visible('entity_relations', changed)['mechanism'] == '합성 메커니즘 RV4')
    print('unprocessed', [(t, s, n) for t, s, n, _ in changes.unprocessed(pg)])
    work.close()
    origin.close()
    os.remove(WORK)


def restore():
    state = json.load(open(STATE))
    pg.execute("DELETE FROM collected_row_revisions WHERE table_name='entities' AND row_data->>'id'=%s", (str(state['entity']),))
    for ident, row in state['originals']['entity_relations'].items():
        pg.execute("UPDATE question_graph_overlay_rows SET row_data=%s WHERE table_name='entity_relations' AND row_data->>'id'=%s",
                   (Jsonb(row), ident))
        pg.execute('UPDATE question_graph_overlay_relations SET source_row=%s WHERE id=%s', (Jsonb(row), int(ident)))
    pg.execute("DELETE FROM question_graph_overlay_rows WHERE table_name='narrative_edge_evidence' AND row_data->>'id'=%s",
               (str(state['evidence']),))
    pg.execute('DELETE FROM question_graph_overlay_evidence WHERE id=%s', (state['evidence'],))
    print('kept rows', pg.execute('DELETE FROM collected_change_conflicts WHERE run_id=%s', (RUN,)).rowcount,
          'entity back', visible('entities', state['entity']) == state['originals']['entities'][str(state['entity'])])
    os.remove(STATE)


{'run': run, 'restore': restore}[sys.argv[1]]()

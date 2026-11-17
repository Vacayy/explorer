"""Records the user made on the MacBook after the 11-14 base, added to the candidate's own tables inside the cutover
freeze right after R3 (R3b; architect #3 6944631236).

The candidate keeps conversations, questions, studies and proxy boards in its own PG tables, which neither the
publication (R2) nor the ledger re-import (R3) touches. Per table, against the 11-14 base:
- a MacBook row the base did not have is added, owned by the operator, under a new id from the candidate's own
  sequence (the candidate may have used the old number); children follow their parents through the map
  (candidate_id_remap, origin 'macbook'), and a row already mapped is never added again;
- a base row changed only on the MacBook takes the MacBook value; changed on both sides, the MacBook value too, the
  candidate's archived in candidate_record_archive (R3's rule);
- a base row the MacBook removed stays, and is only listed.
Old numeric URLs are not reinterpreted.
"""
import hashlib
import json

from psycopg import sql
from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

# (table, key columns, {column: parent table}) in parent-first order. A one-column 'id' key is renumbered.
TABLES = (('conversations', ('id',), {}),
          ('chat_messages', ('id',), {'conversation_id': 'conversations'}),
          ('chat_entity_links', ('message_id', 'entity_id'), {'message_id': 'chat_messages'}),
          ('questions', ('id',), {}),
          ('sub_questions', ('id',), {'question_id': 'questions'}),
          ('question_reports', ('id',), {'question_id': 'questions'}),
          ('proxy_registry', ('id',), {'sub_question_id': 'sub_questions'}),
          ('proxy_boards', ('id',), {'question_id': 'questions'}),
          ('proxy_board_items', ('board_id', 'proxy_id'), {'board_id': 'proxy_boards', 'proxy_id': 'proxy_registry'}),
          ('proxy_observations', ('id',), {'proxy_id': 'proxy_registry'}),
          ('proxy_scans', ('proxy_id', 'transcript_id'), {'proxy_id': 'proxy_registry'}),
          ('scenarios', ('topic',), {'question_id': 'questions'}),
          ('observations', ('id',), {}),
          ('study_projects', ('id',), {'conversation_id': 'conversations'}),
          ('study_sessions', ('id',), {'project_id': 'study_projects', 'conversation_id': 'conversations'}),
          ('study_turns', ('id',), {'study_id': 'study_sessions'}),
          ('study_annotations', ('id',), {'study_id': 'study_sessions'}),
          ('study_annotation_actions', ('id',), {'study_id': 'study_sessions', 'annotation_id': 'study_annotations',
                                                 'parent_id': 'study_annotation_actions',
                                                 'retry_of': 'study_annotation_actions'}),
          ('study_project_members', ('project_id', 'study_id'), {'project_id': 'study_projects', 'study_id': 'study_sessions'}),
          ('study_project_turns', ('id',), {'project_id': 'study_projects'}))
# The operator owns what is added: (ownership table, its id column) per owned table.
OWNERS = {'questions': ('question_principals', 'question_id'), 'study_sessions': ('study_principals', 'study_id'),
          'study_projects': ('study_project_principals', 'project_id')}


def _digest(row, columns):
    return hashlib.sha256(json.dumps([row.get(c) for c in columns], ensure_ascii=False, default=str).encode()).hexdigest()


def _rows(db, table, key):
    if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone() is None:
        return [], {}
    columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
    return columns, {tuple(row[columns.index(k)] for k in key): dict(zip(columns, row))
                     for row in db.execute(f'SELECT * FROM "{table}"')}


def _initialize(pg):
    pg.execute("ALTER TABLE candidate_id_remap ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'candidate'")
    pg.execute('CREATE TABLE IF NOT EXISTS candidate_record_archive (id BIGSERIAL PRIMARY KEY, ledger TEXT NOT NULL, '
               'record_key JSONB NOT NULL, candidate_row JSONB, source_row JSONB, computed BOOLEAN NOT NULL, '
               "reason TEXT NOT NULL DEFAULT 'conflict: MacBook value applied', archived_at TIMESTAMPTZ NOT NULL DEFAULT now())")


def apply(pg, base, source, *, operator):
    """Add, update and list as described above, in one transaction; returns counts per table."""
    _guard(pg)
    report = {}
    with pg.transaction():
        _initialize(pg)
        mapped = {}  # table -> {old id: new id}
        for kind, old, new in pg.execute("SELECT kind, old_id, new_id FROM candidate_id_remap WHERE origin='macbook'"):
            mapped.setdefault(kind.removeprefix('macbook:'), {})[old] = new
        for table, key, parents in TABLES:
            if pg.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0] is None:
                continue
            columns, src = _rows(source, table, key)
            if not columns:
                continue
            _, old = _rows(base, table, key)
            pg_columns = [r[0] for r in pg.execute('SELECT column_name FROM information_schema.columns WHERE '
                                                   'table_schema=current_schema() AND table_name=%s', (table,))]
            columns = [c for c in columns if c in pg_columns]
            content = [c for c in columns if c not in key]
            renumber = key == ('id',)
            counts = {'added': 0, 'applied': 0, 'conflict': 0, 'removed_on_macbook': 0, 'skipped_mapped': 0}
            table_map = mapped.setdefault(table, {})

            def translate(row):
                out = dict(row)
                for column, parent in parents.items():
                    if out.get(column) is not None and out[column] in mapped.get(parent, {}):
                        out[column] = mapped[parent][out[column]]
                return out
            for ident, row in sorted(src.items(), key=lambda item: str(item[0])):
                if ident in old:
                    continue
                if renumber and ident[0] in table_map:
                    counts['skipped_mapped'] += 1
                    continue
                values = translate(row)
                names = [c for c in columns if not (renumber and c == 'id')]
                if not renumber:
                    where = sql.SQL(' AND ').join(sql.SQL('{} IS NOT DISTINCT FROM %s').format(sql.Identifier(k)) for k in key)
                    if pg.execute(sql.SQL('SELECT 1 FROM {} WHERE ').format(sql.Identifier(table)) + where,
                                  [values[k] for k in key]).fetchone():
                        counts['skipped_mapped'] += 1  # added before, or the candidate made the same one
                        continue
                inserted = pg.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}){}').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, names)),
                    sql.SQL(',').join([sql.Placeholder()] * len(names)),
                    sql.SQL(' RETURNING id') if renumber else sql.SQL('')), [values[c] for c in names])
                counts['added'] += 1
                if renumber:
                    new = inserted.fetchone()[0]
                    table_map[ident[0]] = new
                    pg.execute('INSERT INTO candidate_id_remap (kind, old_id, new_id, origin) VALUES (%s,%s,%s,%s)',
                               (f'macbook:{table}', ident[0], new, 'macbook'))
                    if table in OWNERS:
                        owner_table, column = OWNERS[table]
                        pg.execute(sql.SQL('INSERT INTO {} ({}, principal) VALUES (%s,%s) ON CONFLICT DO NOTHING').format(
                            sql.Identifier(owner_table), sql.Identifier(column)), (new, operator))
            # Base rows: the MacBook's change applies (conflict: archived first); removals are listed only.
            for ident, before in old.items():
                after = src.get(ident)
                if after is None:
                    counts['removed_on_macbook'] += 1
                    continue
                if _digest(after, content) == _digest(before, content):
                    continue
                where = sql.SQL(' AND ').join(sql.SQL('{} = %s').format(sql.Identifier(k)) for k in key)
                cursor = pg.execute(sql.SQL('SELECT {} FROM {} WHERE ').format(
                    sql.SQL(',').join(map(sql.Identifier, content)), sql.Identifier(table)) + where, list(ident))
                current = cursor.fetchone()
                candidate = dict(zip(content, current)) if current else None
                if candidate is not None and _digest(candidate, content) == _digest(after, content):
                    continue  # already the MacBook's
                if candidate is not None and _digest(candidate, content) != _digest(before, content):
                    pg.execute('INSERT INTO candidate_record_archive (ledger, record_key, candidate_row, source_row, computed) '
                               'VALUES (%s,%s,%s,%s,false)', (table, Jsonb(list(ident)), Jsonb(candidate, dumps=_dumps),
                                                              Jsonb(after, dumps=_dumps)))
                    counts['conflict'] += 1
                if candidate is None:
                    continue  # removed in the candidate: kept removed (candidate-only change)
                pg.execute(sql.SQL('UPDATE {} SET {} WHERE ').format(sql.Identifier(table), sql.SQL(',').join(
                    sql.SQL('{} = %s').format(sql.Identifier(c)) for c in content)) + where,
                    [translate(after)[c] for c in content] + list(ident))
                counts['applied'] += 1
            report[table] = {k: v for k, v in counts.items() if v}
    return {table: counts for table, counts in report.items() if counts}


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)

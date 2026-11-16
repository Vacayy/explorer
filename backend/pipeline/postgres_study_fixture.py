"""Private, disposable study import and annotation operations.

The source must share one SQLite read transaction with the chat import. This
module neither publishes routes nor starts queued model jobs.
"""
import hashlib
import json

from fastapi import HTTPException
from psycopg import sql
from psycopg.rows import dict_row
from pipeline.postgres_graph_fixture import _guard

TABLES = {
    'study_projects': 'id title note revision conversation_id created_at updated_at',
    'study_sessions': 'id document_id project_id title source_url source_type published_at body_kind body content_hash conversation_id created_at updated_at',
    'study_annotations': 'id study_id kind start_offset end_offset exact comment revision deleted_at created_at updated_at intent',
    'study_project_members': 'project_id study_id removed_at',
    'study_turns': 'id study_id conversation_id message_id request_key question context_json status error created_at finished_at',
    'study_project_turns': 'id project_id conversation_id message_id request_key question context_json status error created_at finished_at',
    'study_annotation_actions': 'id study_id annotation_id owner_key intent request_key request_hash prompt_version parent_id retry_of question context_json conversation_id status result_json error claim_token created_at started_at finished_at',
}
CHAT_COLUMNS = {
    'conversations': 'id title anchor_entity_id channel chat_id summary state_json created_at updated_at',
    'chat_messages': 'id conversation_id role content citations_json gaps_json model route_json attachments_json created_at',
    'chat_entity_links': 'message_id entity_id link_type',
}


# Report existing broken links without silently discarding them. These queries
# work in both databases and include chat ownership for turn messages.
RELATION_GAPS = {
    'session_project': "SELECT count(*) FROM study_sessions s LEFT JOIN study_projects p ON p.id=s.project_id WHERE s.project_id<>0 AND p.id IS NULL",
    'session_chat': "SELECT count(*) FROM study_sessions s LEFT JOIN conversations c ON c.id=s.conversation_id WHERE s.conversation_id IS NOT NULL AND c.id IS NULL",
    'project_chat': "SELECT count(*) FROM study_projects p LEFT JOIN conversations c ON c.id=p.conversation_id WHERE p.conversation_id IS NOT NULL AND c.id IS NULL",
    'annotation_session': "SELECT count(*) FROM study_annotations a LEFT JOIN study_sessions s ON s.id=a.study_id WHERE s.id IS NULL",
    'member': "SELECT count(*) FROM study_project_members m LEFT JOIN study_sessions s ON s.id=m.study_id LEFT JOIN study_projects p ON p.id=m.project_id WHERE s.id IS NULL OR p.id IS NULL",
    'study_turn': "SELECT count(*) FROM study_turns t LEFT JOIN study_sessions s ON s.id=t.study_id LEFT JOIN conversations c ON c.id=t.conversation_id LEFT JOIN chat_messages m ON m.id=t.message_id AND m.conversation_id=t.conversation_id WHERE s.id IS NULL OR c.id IS NULL OR m.id IS NULL",
    'project_turn': "SELECT count(*) FROM study_project_turns t LEFT JOIN study_projects p ON p.id=t.project_id LEFT JOIN conversations c ON c.id=t.conversation_id LEFT JOIN chat_messages m ON m.id=t.message_id AND m.conversation_id=t.conversation_id WHERE p.id IS NULL OR c.id IS NULL OR m.id IS NULL",
    'action_chain': "SELECT count(*) FROM study_annotation_actions a LEFT JOIN study_annotation_actions p ON p.id=a.parent_id LEFT JOIN study_annotation_actions r ON r.id=a.retry_of WHERE (a.parent_id IS NOT NULL AND p.id IS NULL) OR (a.retry_of IS NOT NULL AND r.id IS NULL)",
    'action_annotation_chat': "SELECT count(*) FROM study_annotation_actions a LEFT JOIN study_annotations n ON n.id=a.annotation_id AND n.study_id=a.study_id LEFT JOIN conversations c ON c.id=a.conversation_id WHERE n.id IS NULL OR (a.conversation_id IS NOT NULL AND c.id IS NULL)",
}


def import_studies(source, target):
    """Import all study records atomically into an empty disposable schema.

    Existing chat must equal the *same* read snapshot; no pending action is run.
    An import is only a candidate, not an incremental sync or cutover.
    """
    _guard(target)
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('An active query-only SQLite snapshot is required')
    rows = {}
    for table, spec in TABLES.items():
        columns = spec.split()
        info = source.execute('PRAGMA table_info(' + table + ')').fetchall()
        if [r[1] for r in info] != columns:
            raise ValueError('Unsupported source schema: ' + table)
        rows[table] = [tuple(r) for r in source.execute('SELECT ' + ','.join(columns) + ' FROM ' + table)]
    with target.transaction():
        for table, spec in CHAT_COLUMNS.items():
            columns = spec.split()
            local = sorted(tuple(r) for r in source.execute('SELECT ' + ','.join(columns) + ' FROM ' + table))
            remote = sorted(tuple(r) for r in target.execute(sql.SQL('SELECT {} FROM {}').format(
                sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))))
            if local != remote:
                raise ValueError('Chat snapshot mismatch: ' + table)
        for table, spec in TABLES.items():
            columns = spec.split()
            info = source.execute('PRAGMA table_info(' + table + ')').fetchall()
            defs = []
            for _, name, kind, required, _, pk in info:
                if kind not in ('INTEGER', 'TEXT'):
                    raise ValueError('Unsupported column type')
                datatype = sql.SQL('BIGINT') if kind == 'INTEGER' else sql.SQL('TEXT')
                identity = sql.SQL(' GENERATED BY DEFAULT AS IDENTITY') if name == 'id' and pk else sql.SQL('')
                nullable = sql.SQL(' NOT NULL') if required or pk else sql.SQL('')
                defs.append(sql.SQL('{} {}{}{}').format(sql.Identifier(name), datatype, identity, nullable))
            primary = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
            if primary:
                defs.append(sql.SQL('PRIMARY KEY ({})').format(sql.SQL(',').join(map(sql.Identifier, primary))))
            target.execute(sql.SQL('CREATE TABLE {} ({})').format(sql.Identifier(table), sql.SQL(',').join(defs)))
            if rows[table]:
                with target.cursor() as cur:
                    cur.executemany(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                        sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                        sql.SQL(',').join([sql.Placeholder()] * len(columns))), rows[table])
            if 'id' in columns:
                has_sequence = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
                prior = source.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone() if has_sequence else None
                high_water = int(prior[0]) if prior and prior[0] is not None else 0
                target.execute('SELECT setval(pg_get_serial_sequence(%s,%s), GREATEST(COALESCE((SELECT max(id) FROM '
                               + table + '),0),%s,1), (GREATEST(COALESCE((SELECT max(id) FROM '
                               + table + '),0),%s)>0))', (table, 'id', high_water, high_water))
        target.execute('CREATE UNIQUE INDEX study_session_document_project ON study_sessions(document_id,project_id)')
        target.execute('CREATE UNIQUE INDEX study_turn_request ON study_turns(study_id,request_key)')
        target.execute('CREATE UNIQUE INDEX study_project_turn_request ON study_project_turns(project_id,request_key)')
        target.execute('CREATE UNIQUE INDEX study_action_request ON study_annotation_actions(study_id,request_key)')
        target.execute("CREATE UNIQUE INDEX study_action_running ON study_annotation_actions(owner_key) WHERE status='running'")
        for name, query in RELATION_GAPS.items():
            if source.execute(query).fetchone()[0] != target.execute(query).fetchone()[0]:
                raise ValueError('Study relation mismatch: ' + name)
    return {name: len(value) for name, value in rows.items()}


class StudyFixture:
    """Study read and annotation mutations against the same isolated PG schema."""
    def __init__(self, connect):
        self.connect = connect

    def open_document(self, document_id):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                # Imported fixture tables do not retain SQLite UNIQUE clauses.
                # Serialize this document's create-or-open operation explicitly.
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('study:0:' + str(document_id),))
                cur.execute('SELECT id FROM study_sessions WHERE document_id=%s AND project_id=0', (document_id,))
                row = cur.fetchone()
                if row:
                    return {'id': row['id']}
                cur.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(document_id),))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(404, '수집 자료를 찾을 수 없습니다')
                doc = row['row_data']
                body = doc.get('markdown') or doc.get('raw_content') or ''
                if not body.strip() or len(body) > 1_000_000:
                    raise HTTPException(422, '텍스트가 없거나 본문이 너무 큽니다.')
                kind = '영상 보관 본문 · AI 정리본일 수 있음' if doc.get('source_type') == 'youtube' and doc.get('markdown') else '보관 원문'
                cur.execute("""INSERT INTO study_sessions(document_id,project_id,title,source_url,source_type,published_at,body_kind,body,content_hash,created_at,updated_at)
                    VALUES(%s,0,%s,%s,%s,%s,%s,%s,%s,to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS'),to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')) RETURNING id""",
                    (document_id, doc.get('title') or '제목 없는 자료', doc.get('url'), doc.get('source_type'), doc.get('published_at'), kind, body, hashlib.sha256(body.encode()).hexdigest()))
                return {'id': cur.fetchone()['id']}

    def listing(self):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute("""SELECT s.id,s.title,s.document_id,s.updated_at,s.conversation_id,
                    (SELECT count(*) FROM study_annotations a WHERE a.study_id=s.id AND a.deleted_at IS NULL) AS annotation_count
                    FROM study_sessions s WHERE s.project_id=0 ORDER BY s.updated_at DESC LIMIT 100""")
                return list(cur.fetchall())

    def read(self, study_id):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT * FROM study_sessions WHERE id=%s', (study_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(404, '스터디를 찾을 수 없습니다')
                cur.execute('SELECT * FROM study_annotations WHERE study_id=%s AND deleted_at IS NULL ORDER BY start_offset,id', (study_id,))
                row['annotations'] = list(cur.fetchall())
                cur.execute('SELECT * FROM study_turns WHERE study_id=%s ORDER BY id', (study_id,))
                row['turns'] = [{**r, 'context': json.loads(r['context_json'])} for r in cur.fetchall()]
                return row

    def add_annotation(self, study_id, body):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT body FROM study_sessions WHERE id=%s FOR UPDATE', (study_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(404, '스터디를 찾을 수 없습니다')
                text = row['body']
                if not 0 <= body.start < body.end <= len(text) or text[body.start:body.end] != body.exact:
                    raise HTTPException(422, '선택 위치와 고정된 원문이 일치하지 않습니다. 새로고침 후 다시 선택해 주세요.')
                cur.execute("""INSERT INTO study_annotations(study_id,kind,start_offset,end_offset,exact,comment,revision,intent,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,1,'highlight',to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS'),to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')) RETURNING *""",
                    (study_id, body.kind, body.start, body.end, body.exact, body.comment))
                result = cur.fetchone()
                cur.execute("UPDATE study_sessions SET updated_at=to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS') WHERE id=%s", (study_id,))
                return result

    def edit_annotation(self, study_id, annotation_id, body):
        with self.connect() as c:
            _guard(c)
            found = c.execute('SELECT 1 FROM study_sessions WHERE id=%s', (study_id,)).fetchone()
            if not found:
                raise HTTPException(404, '스터디를 찾을 수 없습니다')
            result = c.execute("""UPDATE study_annotations SET comment=%s,revision=revision+1,
                updated_at=to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS'),
                deleted_at=CASE WHEN %s THEN to_char(timezone('utc',now()),'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"') ELSE NULL END
                WHERE id=%s AND study_id=%s AND revision=%s AND deleted_at IS NULL""",
                (body.comment, body.delete, annotation_id, study_id, body.revision))
            if result.rowcount != 1:
                raise HTTPException(409, '다른 화면에서 주석이 변경됐습니다. 다시 불러온 뒤 확인해 주세요.')
            c.execute("UPDATE study_sessions SET updated_at=to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS') WHERE id=%s", (study_id,))
            return {'ok': True}

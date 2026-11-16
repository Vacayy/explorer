"""Captured question records and existing read contracts in disposable PG.

SQLite is only a private in-memory projection of PG rows for existing reads;
it never points at the operational database. Any writable projection is
private and committed back only through an explicit locked PG transaction.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from psycopg.types.json import Jsonb
from pipeline import questions, question_report
from pipeline.postgres_graph_fixture import _guard

TABLES=('questions','sub_questions','proxy_registry','proxy_observations','question_reports','proxy_scans','scenarios','transcripts','raw_documents','entity_relations','knowledge','knowledge_falsifiers','observations','transcript_follow','narrative_edge_evidence')
FILTERS={
    'scenarios': 'WHERE question_id IS NOT NULL',
    'transcripts': 'WHERE id IN (SELECT transcript_id FROM proxy_observations WHERE transcript_id IS NOT NULL)',
    'raw_documents': 'WHERE id IN (SELECT source_doc_id FROM questions WHERE source_doc_id IS NOT NULL)',
    'entity_relations': 'WHERE id IN (SELECT entity_relation_id FROM narrative_edge_evidence WHERE narrative_id IN (SELECT narrative_id FROM questions WHERE narrative_id IS NOT NULL)) OR narrative_id IN (SELECT narrative_id FROM questions WHERE narrative_id IS NOT NULL)',
    'narrative_edge_evidence': 'WHERE narrative_id IN (SELECT narrative_id FROM questions WHERE narrative_id IS NOT NULL)',
    'knowledge': 'WHERE id IN (SELECT promoted_knowledge_id FROM entity_relations WHERE narrative_id IN (SELECT narrative_id FROM questions WHERE narrative_id IS NOT NULL) AND promoted_knowledge_id IS NOT NULL)',
    'knowledge_falsifiers': 'WHERE knowledge_id IN (SELECT promoted_knowledge_id FROM entity_relations WHERE narrative_id IN (SELECT narrative_id FROM questions WHERE narrative_id IS NOT NULL) AND promoted_knowledge_id IS NOT NULL)',
}


def import_questions(source, target):
    _guard(target)
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('An active query-only SQLite snapshot is required')
    with target.transaction():
        target.execute('''CREATE TABLE question_capture_tables (
            table_name TEXT PRIMARY KEY,columns JSONB NOT NULL,schema_sql TEXT NOT NULL,row_count BIGINT NOT NULL)''')
        target.execute('''CREATE TABLE question_capture_rows (
            table_name TEXT NOT NULL REFERENCES question_capture_tables(table_name),row_ordinal BIGINT NOT NULL,
            row_data JSONB NOT NULL,PRIMARY KEY(table_name,row_ordinal))''')
        target.execute('CREATE TABLE question_capture_sequences (table_name TEXT PRIMARY KEY,sequence_value BIGINT NOT NULL)')
        target.execute("""CREATE TABLE question_report_attempts (
            token UUID PRIMARY KEY, question_id BIGINT NOT NULL, input_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running','completed','failed','stale','unknown')),
            started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), finished_at TIMESTAMPTZ)""")
        target.execute("CREATE UNIQUE INDEX question_report_one_unresolved ON question_report_attempts(question_id) WHERE status IN ('running','unknown')")
        has_sequence=source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
        if has_sequence:
            sequences=source.execute('SELECT name,seq FROM sqlite_sequence WHERE name IN ('+','.join('?' for _ in TABLES)+')',TABLES).fetchall()
            if sequences:
                with target.cursor() as cur:
                    cur.executemany('INSERT INTO question_capture_sequences VALUES (%s,%s)',(tuple(row) for row in sequences))
        counts={}
        for table in TABLES:
            schema=source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not schema or not schema[0]:raise ValueError('Missing source table: '+table)
            columns=[r[1] for r in source.execute('PRAGMA table_info("'+table+'")')]
            cursor=source.execute('SELECT * FROM "'+table+'" '+FILTERS.get(table,''))
            values=[dict(zip(columns,tuple(row))) for row in cursor]
            counts[table]=len(values)
            target.execute('INSERT INTO question_capture_tables VALUES (%s,%s,%s,%s)',(table,Jsonb(columns),schema[0],len(values)))
            if values:
                with target.cursor() as cur:
                    cur.executemany('INSERT INTO question_capture_rows VALUES (%s,%s,%s)',
                                    ((table,i,Jsonb(row)) for i,row in enumerate(values)))
    return counts


@contextmanager
def _projection(connect, *, writable=False):
    uri='file:question-fixture-'+uuid.uuid4().hex+'?mode=memory&cache=shared'
    root=sqlite3.connect(uri,uri=True);root.row_factory=sqlite3.Row
    try:
        with connect() as pg:
            pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(pg)
            metadata=pg.execute('SELECT table_name,columns,schema_sql,row_count FROM question_capture_tables ORDER BY table_name').fetchall()
            if {m[0] for m in metadata} != set(TABLES):raise ValueError('Incomplete question capture')
            for table,columns,ddl,count in metadata:
                root.execute(ddl)
                actual=[r['name'] for r in root.execute('PRAGMA table_info("'+table+'")')]
                if actual!=columns:raise ValueError('Question capture schema mismatch')
                rows=pg.execute('SELECT row_data FROM question_capture_rows WHERE table_name=%s ORDER BY row_ordinal',(table,)).fetchall()
                if len(rows)!=count:raise ValueError('Question capture row count mismatch')
                names=','.join('"'+name.replace('"','""')+'"' for name in columns)
                root.executemany('INSERT INTO "'+table+'" ('+names+') VALUES ('+','.join('?' for _ in columns)+')',
                                 (tuple(row[0].get(name) for name in columns) for row in rows))
            sequences=pg.execute('SELECT table_name,sequence_value FROM question_capture_sequences').fetchall()
            for table,seq in sequences:
                if table not in TABLES:raise ValueError('Unknown question sequence')
                current=root.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
                if current and current[0] > seq:raise ValueError('Question sequence predates captured rows')
                if current:root.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?',(seq,table))
                else:root.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)',(table,seq))
        root.commit()
        def connection():
            conn=sqlite3.connect(uri,uri=True);conn.row_factory=sqlite3.Row
            if not writable:conn.execute('PRAGMA query_only=ON')
            return conn
        yield connection
    finally:root.close()


class QuestionsFixture:
    def __init__(self, connect):self.connect=connect
    def listing(self, narrative_id=None,status=None):
        with _projection(self.connect) as factory:return questions.list_questions(narrative_id,status,connection_factory=factory)
    def detail(self,question_id):
        with _projection(self.connect) as factory:
            result=questions.get_tree(question_id,connection_factory=factory)
        if 'error' not in result:
            with self.connect() as pg:
                _guard(pg)
                pg.execute("""UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{last_viewed_at}',
                    to_jsonb(to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')),true)
                    WHERE table_name='questions' AND row_data->>'id'=%s""",(str(question_id),))
        return result

    def dismiss(self,question_id):
        with self.connect() as pg:
            _guard(pg)
            pg.execute("""UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{status}',to_jsonb('dismissed'::text),true)
                WHERE table_name='questions' AND row_data->>'id'=%s""",(str(question_id),))
    def synthesis(self,question_id):
        with _projection(self.connect) as factory:return question_report.synthesis_status(question_id,connection_factory=factory)
    def proxy(self,proxy_id):
        with _projection(self.connect) as factory:return questions.get_proxy_detail(proxy_id,connection_factory=factory)

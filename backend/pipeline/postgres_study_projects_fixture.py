"""Study project operations in a disposable PostgreSQL candidate only."""
import hashlib
import json

from fastapi import HTTPException
from psycopg.rows import dict_row
from pipeline.postgres_graph_fixture import _guard

NOW = "to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')"


class StudyProjectsFixture:
    def __init__(self, connect):
        self.connect = connect

    @staticmethod
    def _project(cur, pid, *, lock=False):
        cur.execute('SELECT * FROM study_projects WHERE id=%s' + (' FOR UPDATE' if lock else ''), (pid,))
        project = cur.fetchone()
        if not project:
            raise HTTPException(404, '스터디 프로젝트를 찾을 수 없습니다.')
        return project

    def listing(self):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute('''SELECT p.*,(SELECT count(*) FROM study_project_members m
                    WHERE m.project_id=p.id AND m.removed_at IS NULL) AS document_count
                    FROM study_projects p ORDER BY updated_at DESC,id DESC LIMIT 200''')
                return list(cur.fetchall())

    def create(self, title):
        if not title.strip():
            raise HTTPException(422, '프로젝트 이름을 입력해 주세요.')
        with self.connect() as c:
            _guard(c)
            row = c.execute(f"INSERT INTO study_projects(title,note,revision,created_at,updated_at) VALUES(%s,'',1,{NOW},{NOW}) RETURNING id", (title.strip(),)).fetchone()
            return {'id': row[0]}

    def read(self, pid):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                project = self._project(cur, pid)
                cur.execute('''SELECT s.id,s.document_id,s.title,s.source_type,s.source_url,s.published_at,length(s.body) AS body_length,
                    (SELECT count(*) FROM study_annotations a WHERE a.study_id=s.id AND a.deleted_at IS NULL) AS annotation_count
                    FROM study_project_members m JOIN study_sessions s ON s.id=m.study_id
                    WHERE m.project_id=%s AND m.removed_at IS NULL ORDER BY s.id''', (pid,))
                project['documents'] = list(cur.fetchall())
                cur.execute('SELECT * FROM study_project_turns WHERE project_id=%s ORDER BY id', (pid,))
                project['turns'] = [{**r, 'context': json.loads(r['context_json'])} for r in cur.fetchall()]
                return project

    def edit(self, pid, body):
        if not body.title.strip():
            raise HTTPException(422, '프로젝트 이름을 입력해 주세요.')
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                self._project(cur, pid, lock=True)
                cur.execute(f'''UPDATE study_projects SET title=%s,note=%s,revision=revision+1,updated_at={NOW}
                    WHERE id=%s AND revision=%s RETURNING *''', (body.title.strip(), body.note, pid, body.revision))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(409, '다른 화면에서 노트가 변경됐습니다. 입력을 보관하고 최신 내용을 다시 확인해 주세요.')
                return row

    def search(self, q):
        value = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute("""SELECT (row_data->>'id')::bigint AS id,row_data->>'title' AS title,
                    row_data->>'source_type' AS source_type,row_data->>'published_at' AS published_at,row_data->>'url' AS url
                    FROM legacy_snapshot_rows WHERE table_name='raw_documents'
                    AND (row_data->>'title' ILIKE %s OR row_data->>'url' ILIKE %s)
                    AND length(coalesce(nullif(row_data->>'markdown',''),row_data->>'raw_content',''))>0
                    ORDER BY (row_data->>'id')::bigint DESC LIMIT 50""", (value,value))
                return list(cur.fetchall())

    def add_documents(self, pid, ids):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                self._project(cur, pid, lock=True)
                sessions = []
                for doc_id in dict.fromkeys(ids):
                    cur.execute('SELECT id FROM study_sessions WHERE document_id=%s AND project_id=%s', (doc_id, pid))
                    existing = cur.fetchone()
                    if existing:
                        sid = existing['id']
                    else:
                        cur.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(doc_id),))
                        row = cur.fetchone()
                        if not row:
                            raise HTTPException(404, '선택한 수집 자료를 찾을 수 없습니다.')
                        doc = row['row_data']
                        text = doc.get('markdown') or doc.get('raw_content') or ''
                        if not text.strip() or len(text) > 1_000_000:
                            raise HTTPException(422, '선택한 자료에 읽을 텍스트가 없거나 본문이 너무 큽니다.')
                        kind = '영상 보관 본문 · AI 정리본일 수 있음' if doc.get('source_type') == 'youtube' and doc.get('markdown') else '보관 원문'
                        cur.execute(f'''INSERT INTO study_sessions(document_id,project_id,title,source_url,source_type,published_at,body_kind,body,content_hash,created_at,updated_at)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,{NOW},{NOW}) RETURNING id''',
                            (doc_id,pid,doc.get('title') or '제목 없는 자료',doc.get('url'),doc.get('source_type'),doc.get('published_at'),kind,text,hashlib.sha256(text.encode()).hexdigest()))
                        sid = cur.fetchone()['id']
                    cur.execute('''INSERT INTO study_project_members(project_id,study_id) VALUES(%s,%s)
                        ON CONFLICT(project_id,study_id) DO UPDATE SET removed_at=NULL''', (pid,sid))
                    sessions.append(sid)
                cur.execute(f'UPDATE study_projects SET updated_at={NOW} WHERE id=%s', (pid,))
                return {'study_ids': sessions}

    def add_clip(self, pid, body):
        if not body.title.strip() or not body.text.strip():
            raise HTTPException(422, '자료 제목과 본문을 입력해 주세요.')
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                self._project(cur, pid, lock=True)
                cur.execute(f'''INSERT INTO study_sessions(project_id,title,source_url,source_type,body_kind,body,content_hash,created_at,updated_at)
                    VALUES(%s,%s,%s,'note','직접 붙여넣은 자료',%s,%s,{NOW},{NOW}) RETURNING id''',
                    (pid,body.title.strip(),body.url,body.text,hashlib.sha256(body.text.encode()).hexdigest()))
                sid=cur.fetchone()['id']
                cur.execute('INSERT INTO study_project_members(project_id,study_id) VALUES(%s,%s)', (pid,sid))
                cur.execute(f'UPDATE study_projects SET updated_at={NOW} WHERE id=%s', (pid,))
                return {'study_ids':[sid]}

    def remove(self, pid, sid):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                self._project(cur,pid,lock=True)
                cur.execute(f'UPDATE study_project_members SET removed_at={NOW} WHERE project_id=%s AND study_id=%s',(pid,sid))
                cur.execute(f'UPDATE study_projects SET updated_at={NOW} WHERE id=%s',(pid,))
                return {'ok':True}

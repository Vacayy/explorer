"""Independent study projects. Bookmarks are never read or written here."""
import hashlib
import json
from types import SimpleNamespace
from fastapi import HTTPException
from database import get_connection
from pipeline import study

SCHEMA = '''
CREATE TABLE IF NOT EXISTS study_projects (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1, conversation_id INTEGER,
 created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS study_project_members (
 project_id INTEGER NOT NULL REFERENCES study_projects(id),
 study_id INTEGER NOT NULL REFERENCES study_sessions(id), removed_at TEXT,
 PRIMARY KEY(project_id,study_id)
);
CREATE TABLE IF NOT EXISTS study_project_turns (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES study_projects(id),
 conversation_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
 request_key TEXT NOT NULL, question TEXT NOT NULL, context_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', error TEXT,
 created_at TEXT DEFAULT (datetime('now')), finished_at TEXT,
 UNIQUE(project_id,request_key)
);
'''


def migrate(conn):
    """Replace only the old document-unique constraint; preserve IDs and all children."""
    if 'project_id' not in {r[1] for r in conn.execute('PRAGMA table_info(study_sessions)')}:
        conn.commit()
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            statement = study.SCHEMA.split(';')[0].replace('IF NOT EXISTS study_sessions', 'study_sessions_project_migration')
            conn.execute(statement)
            columns = ','.join(r[1] for r in conn.execute('PRAGMA table_info(study_sessions)'))
            conn.execute(f'INSERT INTO study_sessions_project_migration({columns}) SELECT {columns} FROM study_sessions')
            conn.execute('DROP TABLE study_sessions')
            conn.execute('ALTER TABLE study_sessions_project_migration RENAME TO study_sessions')
            for table in ('study_annotations','study_turns'):
                if conn.execute(f'PRAGMA foreign_key_check({table})').fetchone():
                    raise RuntimeError('Study migration failed foreign-key validation')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript(SCHEMA)


def _project(c,pid):
    r=c.execute('SELECT * FROM study_projects WHERE id=?',(pid,)).fetchone()
    if not r: raise HTTPException(404,'스터디 프로젝트를 찾을 수 없습니다.')
    return dict(r)


def create(title):
    if not title.strip(): raise HTTPException(422,'프로젝트 이름을 입력해 주세요.')
    c=get_connection()
    try:
        pid=c.execute('INSERT INTO study_projects(title) VALUES(?)',(title.strip(),)).lastrowid
        c.commit();return {'id':pid}
    finally:c.close()


def listing():
    c=get_connection()
    try:return [dict(r) for r in c.execute('''SELECT p.*,(SELECT count(*) FROM study_project_members m WHERE m.project_id=p.id AND m.removed_at IS NULL) AS document_count
        FROM study_projects p ORDER BY updated_at DESC,id DESC LIMIT 200''')]
    finally:c.close()


def read(pid):
    c=get_connection()
    try:
        p=_project(c,pid)
        p['documents']=[dict(r) for r in c.execute('''SELECT s.id,s.document_id,s.title,s.source_type,s.source_url,s.published_at,length(s.body) AS body_length,
            (SELECT count(*) FROM study_annotations a WHERE a.study_id=s.id AND a.deleted_at IS NULL) AS annotation_count
            FROM study_project_members m JOIN study_sessions s ON s.id=m.study_id
            WHERE m.project_id=? AND m.removed_at IS NULL ORDER BY s.id''',(pid,))]
        p['turns']=[{**dict(r),'context':json.loads(r['context_json'])} for r in c.execute('SELECT * FROM study_project_turns WHERE project_id=? ORDER BY id',(pid,))]
        return p
    finally:c.close()


def edit(pid,body):
    c=get_connection()
    try:
        _project(c,pid)
        if not body.title.strip():raise HTTPException(422,'프로젝트 이름을 입력해 주세요.')
        cur=c.execute("UPDATE study_projects SET title=?,note=?,revision=revision+1,updated_at=datetime('now') WHERE id=? AND revision=?",(body.title.strip(),body.note,pid,body.revision))
        if not cur.rowcount:raise HTTPException(409,'다른 화면에서 노트가 변경됐습니다. 입력을 보관하고 최신 내용을 다시 확인해 주세요.')
        c.commit();return _project(c,pid)
    finally:c.close()


def add_documents(pid,ids):
    c=get_connection()
    try:
        _project(c,pid)
        for doc_id in dict.fromkeys(ids):
            # Existing project snapshots remain usable even if a collector removed its source.
            if c.execute('SELECT 1 FROM study_sessions WHERE document_id=? AND project_id=?',(doc_id,pid)).fetchone():
                continue
            row=c.execute('SELECT markdown,raw_content FROM raw_documents WHERE id=?',(doc_id,)).fetchone()
            if not row:raise HTTPException(404,'선택한 수집 자료를 찾을 수 없습니다.')
            text=row['markdown'] or row['raw_content'] or ''
            if not text.strip() or len(text)>1_000_000:raise HTTPException(422,'선택한 자료에 읽을 텍스트가 없거나 본문이 너무 큽니다.')
    finally:c.close()
    # Open snapshots before membership, with a separate project scope. Re-add reuses annotations.
    sessions=[study.open_document(d,pid)['id'] for d in dict.fromkeys(ids)]
    c=get_connection()
    try:
        c.executemany('INSERT INTO study_project_members(project_id,study_id) VALUES(?,?) ON CONFLICT(project_id,study_id) DO UPDATE SET removed_at=NULL',[(pid,s) for s in sessions])
        c.execute("UPDATE study_projects SET updated_at=datetime('now') WHERE id=?",(pid,));c.commit()
        return {'study_ids':sessions}
    finally:c.close()


def add_clip(pid,body):
    c=get_connection()
    try:
        _project(c,pid)
        if not body.text.strip() or not body.title.strip():raise HTTPException(422,'자료 제목과 본문을 입력해 주세요.')
        sid=c.execute('''INSERT INTO study_sessions(project_id,title,source_url,source_type,body_kind,body,content_hash)
          VALUES(?,?,?,'note','직접 붙여넣은 자료',?,?)''',(pid,body.title.strip(),body.url,body.text,hashlib.sha256(body.text.encode()).hexdigest())).lastrowid
        c.execute('INSERT INTO study_project_members(project_id,study_id) VALUES(?,?)',(pid,sid))
        c.execute("UPDATE study_projects SET updated_at=datetime('now') WHERE id=?",(pid,));c.commit()
        return {'study_ids':[sid]}
    finally:c.close()


def remove(pid,sid):
    c=get_connection()
    try:
        _project(c,pid)
        c.execute("UPDATE study_project_members SET removed_at=datetime('now') WHERE project_id=? AND study_id=?",(pid,sid))
        c.execute("UPDATE study_projects SET updated_at=datetime('now') WHERE id=?",(pid,));c.commit()
        return {'ok':True}
    finally:c.close()


def search(q):
    c=get_connection()
    try:
        value='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        return [dict(r) for r in c.execute('''SELECT id,title,source_type,published_at,url FROM raw_documents
          WHERE (title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\') AND length(coalesce(nullif(markdown,''),raw_content,''))>0
          ORDER BY id DESC LIMIT 50''',(value,value))]
    finally:c.close()


def _context(c,pid,body):
    if not body.question.strip():raise HTTPException(422,'질문을 입력해 주세요.')
    if not body.sources or len({s.study_id for s in body.sources})!=len(body.sources):raise HTTPException(422,'서로 다른 자료를 하나 이상 선택해 주세요.')
    evidence=[];sources=[];annotations=[]
    for source in body.sources:
        if not c.execute('SELECT 1 FROM study_project_members WHERE project_id=? AND study_id=? AND removed_at IS NULL',(pid,source.study_id)).fetchone():
            raise HTTPException(409,'선택한 자료가 프로젝트에서 제거되었습니다. 다시 확인해 주세요.')
        s=study._session(c,source.study_id)
        context=study._context(c,s,SimpleNamespace(question=body.question,action='question',annotations=source.annotations))
        for e in context['evidence']:
            suffix=e['href'].partition('?')[2]
            e['href']=f'/study/projects/{pid}?doc={s["id"]}'+('&'+suffix if suffix else '')
            e['text']=f"출처 발행일: {s['published_at'] or '미상'}\n본문 종류: {s['body_kind']}\n"+e['text']
        evidence.extend(context['evidence']);annotations.extend(context['annotations'])
        sources.append({'study_id':s['id'],'title':s['title'],'source_url':s['source_url'],'published_at':s['published_at'],'body_kind':s['body_kind'],'content_hash':s['content_hash'],'scope':context['scope'],'annotations':context['annotations']})
    if len(evidence)>40 or sum(len(e['text']) for e in evidence)>80000:
        raise HTTPException(422,'자료가 너무 많습니다. 자료 수를 줄이거나 하이라이트를 선택해 주세요(총 80,000자·40개 근거).')
    return {'study_id':None,'project_id':pid,'scope':f'선택 자료 {len(sources)}개 · 주석 {len(annotations)}개', 'sources':sources,'annotations':annotations,'evidence':evidence}


def queue_turn(pid,body):
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE');p=_project(c,pid)
        old=c.execute('SELECT id,conversation_id FROM study_project_turns WHERE project_id=? AND request_key=?',(pid,body.request_key)).fetchone()
        if old:return {**dict(old),'created':False}
        if c.execute("SELECT 1 FROM study_project_turns WHERE project_id=? AND status='pending'",(pid,)).fetchone():raise HTTPException(409,'이전 답변을 생성 중입니다.')
        if not body.question.strip():raise HTTPException(422,'질문을 입력해 주세요.')
        context={'project_id':pid,'study_id':None} if getattr(body,'context_mode','auto')=='continue' else _context(c,pid,body)
        from pipeline.study_coach import prepare
        context=prepare(c,'study_project_turns','project_id',pid,body,context)
        cid=p['conversation_id']
        if not cid or not c.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():
            cid=c.execute("INSERT INTO conversations(channel,title,state_json) VALUES('web',?,'{}')",('스터디 프로젝트 · '+p['title'][:80],)).lastrowid
        last=c.execute('SELECT role FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
        if last and last['role']=='user':raise HTTPException(409,'이 대화에 답변 생성 중인 질문이 있습니다.')
        mid=c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'user',?)",(cid,body.question.strip())).lastrowid
        tid=c.execute('INSERT INTO study_project_turns(project_id,conversation_id,message_id,request_key,question,context_json) VALUES(?,?,?,?,?,?)',(pid,cid,mid,body.request_key,body.question.strip(),json.dumps(context,ensure_ascii=False))).lastrowid
        c.execute("UPDATE study_projects SET conversation_id=?,updated_at=datetime('now') WHERE id=?",(cid,pid))
        c.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?",(cid,));c.commit()
        return {'id':tid,'conversation_id':cid,'created':True}
    finally:c.close()


def execute_turn(tid):
    c=get_connection()
    try:r=dict(c.execute('SELECT * FROM study_project_turns WHERE id=?',(tid,)).fetchone())
    finally:c.close()
    from pipeline.chat import generate_answer
    context=json.loads(r['context_json'])
    try:result=generate_answer(r['conversation_id'],r['question'],study_context=context)
    except Exception:
        from pipeline.conversations import append_assistant
        result={'error':'스터디 답변 생성에 실패했습니다. 다시 시도해 주세요.'}
        append_assistant(r['conversation_id'],result['error'])
    c=get_connection()
    try:
        c.execute("UPDATE study_project_turns SET status=?,error=?,context_json=?,finished_at=datetime('now') WHERE id=? AND status='pending'",('error' if result.get('error') else 'complete',result.get('error'),json.dumps(context,ensure_ascii=False),tid));c.commit()
    finally:c.close()


def recover(pid,tid):
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE');_project(c,pid)
        r=c.execute("SELECT * FROM study_project_turns WHERE id=? AND project_id=? AND status='pending' AND created_at<datetime('now','-10 minutes')",(tid,pid)).fetchone()
        if not r:raise HTTPException(409,'10분 이상 멈춘 요청만 정리할 수 있습니다.')
        error='스터디 답변 요청이 중단됐습니다. 다시 질문해 주세요.'
        last=c.execute('SELECT id,role FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(r['conversation_id'],)).fetchone()
        if last and last['id']==r['message_id'] and last['role']=='user':c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'assistant',?)",(r['conversation_id'],error))
        c.execute("UPDATE study_project_turns SET status='error',error=?,finished_at=datetime('now') WHERE id=?",(error,tid));c.commit();return {'ok':True}
    finally:c.close()

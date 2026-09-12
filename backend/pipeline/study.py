"""Document-focused study: immutable text, durable annotations and per-turn context."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from database import get_connection

SCHEMA = '''
CREATE TABLE IF NOT EXISTS study_sessions (
 id INTEGER PRIMARY KEY, document_id INTEGER, project_id INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL,
 source_url TEXT, source_type TEXT, published_at TEXT, body_kind TEXT NOT NULL,
 body TEXT NOT NULL, content_hash TEXT NOT NULL, conversation_id INTEGER,
 created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
 UNIQUE(document_id, project_id)
);
CREATE TABLE IF NOT EXISTS study_annotations (
 id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL REFERENCES study_sessions(id),
 kind TEXT NOT NULL CHECK(kind IN ('highlight','comment')), start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL, exact TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1, deleted_at TEXT,
 created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS study_annotations_session ON study_annotations(study_id, start_offset);
CREATE TABLE IF NOT EXISTS study_turns (
 id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL REFERENCES study_sessions(id),
 conversation_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
 request_key TEXT NOT NULL, question TEXT NOT NULL, context_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', error TEXT,
 created_at TEXT DEFAULT (datetime('now')), finished_at TEXT,
 UNIQUE(study_id, request_key)
);
'''


def _session(c, study_id):
    row = c.execute('SELECT * FROM study_sessions WHERE id=?', (study_id,)).fetchone()
    if not row:
        raise HTTPException(404, '스터디를 찾을 수 없습니다')
    return dict(row)


def open_document(document_id, project_id=0):
    c = get_connection()
    try:
        old = c.execute('SELECT id FROM study_sessions WHERE document_id=? AND project_id=?', (document_id,project_id)).fetchone()
        if old:
            return {'id': old['id']}
        d = c.execute('SELECT * FROM raw_documents WHERE id=?', (document_id,)).fetchone()
        if not d:
            raise HTTPException(404, '수집 자료를 찾을 수 없습니다')
        body = d['markdown'] or d['raw_content'] or ''
        if not body.strip():
            raise HTTPException(422, '저장된 텍스트가 없습니다. 텍스트가 있는 자료를 선택해 주세요.')
        if len(body) > 1_000_000:
            raise HTTPException(422, '본문이 너무 큽니다. 100만 자 이하 자료를 선택해 주세요.')
        kind = '영상 보관 본문 · AI 정리본일 수 있음' if d['source_type'] == 'youtube' and d['markdown'] else '보관 원문'
        c.execute('''INSERT OR IGNORE INTO study_sessions(document_id,project_id,title,source_url,source_type,published_at,body_kind,body,content_hash)
          VALUES(?,?,?,?,?,?,?,?,?)''', (document_id,project_id,d['title'] or '제목 없는 자료',d['url'],d['source_type'],d['published_at'],kind,body,hashlib.sha256(body.encode()).hexdigest()))
        c.commit()
        return {'id': c.execute('SELECT id FROM study_sessions WHERE document_id=? AND project_id=?',(document_id,project_id)).fetchone()['id']}
    finally:
        c.close()


def list_studies():
    c = get_connection()
    try:
        return [dict(r) for r in c.execute('''SELECT s.id,s.title,s.document_id,s.updated_at,s.conversation_id,
          (SELECT count(*) FROM study_annotations a WHERE a.study_id=s.id AND a.deleted_at IS NULL) AS annotation_count
          FROM study_sessions s WHERE s.project_id=0 ORDER BY s.updated_at DESC LIMIT 100''')]
    finally:
        c.close()


def read_study(study_id):
    c = get_connection()
    try:
        s = _session(c,study_id)
        s['annotations'] = [dict(r) for r in c.execute('SELECT * FROM study_annotations WHERE study_id=? AND deleted_at IS NULL ORDER BY start_offset,id',(study_id,))]
        s['turns'] = [{**dict(r), 'context': json.loads(r['context_json'])} for r in c.execute('SELECT * FROM study_turns WHERE study_id=? ORDER BY id',(study_id,))]
        return s
    finally:
        c.close()


def add_annotation(study_id, body):
    c=get_connection()
    try:
        s=_session(c,study_id)
        start,end=body.start,body.end
        if not 0 <= start < end <= len(s['body']) or s['body'][start:end] != body.exact:
            raise HTTPException(422,'선택 위치와 고정된 원문이 일치하지 않습니다. 새로고침 후 다시 선택해 주세요.')
        cur=c.execute('INSERT INTO study_annotations(study_id,kind,start_offset,end_offset,exact,comment) VALUES(?,?,?,?,?,?)',
                      (study_id,body.kind,start,end,body.exact,body.comment))
        c.execute("UPDATE study_sessions SET updated_at=datetime('now') WHERE id=?",(study_id,))
        c.commit()
        return dict(c.execute('SELECT * FROM study_annotations WHERE id=?',(cur.lastrowid,)).fetchone())
    finally:
        c.close()


def edit_annotation(study_id,annotation_id,body):
    c=get_connection()
    try:
        _session(c,study_id)
        cur=c.execute("UPDATE study_annotations SET comment=?,revision=revision+1,updated_at=datetime('now'),deleted_at=? WHERE id=? AND study_id=? AND revision=? AND deleted_at IS NULL",
                      (body.comment, datetime.now(timezone.utc).isoformat() if body.delete else None,annotation_id,study_id,body.revision))
        if not cur.rowcount:
            raise HTTPException(409,'다른 화면에서 주석이 변경됐습니다. 다시 불러온 뒤 확인해 주세요.')
        c.execute("UPDATE study_sessions SET updated_at=datetime('now') WHERE id=?",(study_id,))
        c.commit()
        return {'ok':True}
    finally:
        c.close()


def _context(c,s,body):
    selected=[]
    if len({a.id for a in body.annotations}) != len(body.annotations):
        raise HTTPException(422,'같은 주석을 중복해서 선택할 수 없습니다.')
    if body.action == 'question' and not body.question.strip():
        raise HTTPException(422,'질문을 입력해 주세요.')
    for ref in body.annotations:
        r=c.execute('SELECT * FROM study_annotations WHERE id=? AND study_id=? AND deleted_at IS NULL',(ref.id,s['id'])).fetchone()
        if not r or r['revision'] != ref.revision:
            raise HTTPException(409,'선택한 주석이 변경됐습니다. 다시 확인해 주세요.')
        selected.append(dict(r))
    if body.action=='summarize' and (not selected or any(a['kind']!='highlight' for a in selected)):
        raise HTTPException(422,'요약할 하이라이트를 선택해 주세요.')
    total=sum(len(a['exact'])+len(a['comment']) for a in selected)
    if total>18000:
        raise HTTPException(422,'선택한 문장과 코멘트가 너무 깁니다. 18,000자 이하로 줄여 주세요.')
    evidence=[]
    for a in selected:
        around=s['body'][max(0,a['start_offset']-400):min(len(s['body']),a['end_offset']+400)]
        text=f"본문 종류: {s['body_kind']}\n[사용자가 지목한 원문]\n{a['exact']}\n[앞뒤 문맥]\n{around}"
        if a['comment']:
            text+=f"\n[사용자의 생각·궁금증 — 원문 작성자의 말이 아님]\n{a['comment']}"
        evidence.append({'kind':'study','title':f"{s['title']} · {'하이라이트' if a['kind']=='highlight' else '코멘트'} {a['id']}",
          'date':s['published_at'],'text':text,'href':f"/study/{s['id']}?annotation={a['id']}",'tool':'study_context'})
    if not evidence:
        evidence=[{'kind':'study','title':s['title'],'date':s['published_at'],
          'text':s['body'][:16000], 'href':f"/study/{s['id']}",'tool':'study_context'}]
    if sum(len(e['text']) for e in evidence)>28000:
        raise HTTPException(422,'주변 문맥을 포함한 자료가 너무 깁니다. 선택 주석 수를 줄여 주세요.')
    return {'study_id':s['id'],'content_hash':s['content_hash'],'body_kind':s['body_kind'],
      'source_url':s['source_url'],'action':body.action,'annotations':selected,'evidence':evidence,
      'scope':'선택 주석과 주변 문맥' if selected else ('본문 앞 16,000자' if len(s['body'])>16000 else '본문 전체')}


def queue_turn(study_id,body):
    """Atomic idempotent admission: one pending turn per study, same chat history."""
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        s=_session(c,study_id)
        old=c.execute('SELECT id,conversation_id FROM study_turns WHERE study_id=? AND request_key=?',(study_id,body.request_key)).fetchone()
        if old:
            return {**dict(old),'created':False}
        if c.execute("SELECT 1 FROM study_turns WHERE study_id=? AND status='pending'",(study_id,)).fetchone():
            raise HTTPException(409,'이전 답변을 생성 중입니다. 완료 후 질문해 주세요.')
        if not body.question.strip() and body.action=='question':raise HTTPException(422,'질문을 입력해 주세요.')
        context={'study_id':study_id} if getattr(body,'context_mode','auto')=='continue' else _context(c,s,body)
        from pipeline.study_coach import prepare
        context=prepare(c,'study_turns','study_id',study_id,body,context)
        question=body.question.strip() or '선택한 하이라이트의 핵심을 요약하고 서로 연결되는 내용을 설명해 주세요.'
        cid=s['conversation_id']
        if cid and not c.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():
            cid=None
        if not cid:
            cid=c.execute("INSERT INTO conversations(channel,title,state_json) VALUES('web',?, '{}')",('스터디 · '+s['title'][:90],)).lastrowid
        last=c.execute('SELECT role FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
        if last and last['role']=='user':
            raise HTTPException(409,'이 대화에 답변 생성 중인 질문이 있습니다.')
        mid=c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'user',?)",(cid,question)).lastrowid
        c.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?",(cid,))
        tid=c.execute('INSERT INTO study_turns(study_id,conversation_id,message_id,request_key,question,context_json) VALUES(?,?,?,?,?,?)',
          (study_id,cid,mid,body.request_key,question,json.dumps(context,ensure_ascii=False))).lastrowid
        c.execute("UPDATE study_sessions SET conversation_id=?,updated_at=datetime('now') WHERE id=?",(cid,study_id))
        c.commit()
        return {'id':tid,'conversation_id':cid,'created':True}
    finally:
        c.close()


def execute_turn(turn_id):
    c=get_connection()
    try:
        r=dict(c.execute('SELECT * FROM study_turns WHERE id=?',(turn_id,)).fetchone())
    finally:
        c.close()
    from pipeline.chat import generate_answer
    context=json.loads(r['context_json'])
    try:
        result=generate_answer(r['conversation_id'],r['question'],study_context=context)
    except Exception:
        from pipeline.conversations import append_assistant
        result={'error':'스터디 답변 생성에 실패했습니다. 다시 시도해 주세요.'}
        append_assistant(r['conversation_id'],result['error'])
    c=get_connection()
    try:
        c.execute("UPDATE study_turns SET status=?,error=?,context_json=?,finished_at=datetime('now') WHERE id=? AND status='pending'",
          ('error' if result.get('error') else 'complete',result.get('error'),json.dumps(context,ensure_ascii=False),turn_id))
        c.commit()
    finally:
        c.close()


def recover_turn(study_id, turn_id):
    """Explicit recovery after the 300-second model deadline plus safety margin."""
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        _session(c,study_id)
        row=c.execute("SELECT *, (julianday('now')-julianday(created_at))*86400 AS age FROM study_turns WHERE id=? AND study_id=?",(turn_id,study_id)).fetchone()
        if not row or row['status']!='pending' or row['age']<600:
            raise HTTPException(409,'10분 이상 멈춘 요청만 정리할 수 있습니다.')
        message='스터디 답변 요청이 중단됐습니다. 같은 내용을 다시 보내 주세요.'
        last=c.execute('SELECT id,role FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(row['conversation_id'],)).fetchone()
        if last and last['id']==row['message_id'] and last['role']=='user':
            c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'assistant',?)",(row['conversation_id'],message))
        c.execute("UPDATE study_turns SET status='error',error=?,finished_at=datetime('now') WHERE id=?",(message,turn_id))
        c.commit()
        return {'ok':True}
    finally:
        c.close()

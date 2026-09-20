"""Durable, FIFO reading actions shared by standalone and project studies.

Each action freezes its evidence and owns a conversation. Only the explicitly
selected answer's ancestry is copied into a follow-up; global chat is untouched.
"""
import hashlib
import json
import re
import uuid
from types import SimpleNamespace
from fastapi import HTTPException
from database import get_connection
from pipeline import study

PROMPT_VERSION = 'study-intents-v1'
QUESTIONS = {
    'explain': '선택한 개념을 쉽게 설명하고, 이 문서의 맥락에서 어떤 의미로 쓰였는지 알려 주세요.',
    'critique': '선택한 주장을 사실·해석·예측으로 구분해 검토하고, 근거와 가장 강한 반론·다른 설명을 바탕으로 판단해 주세요.',
    'related': '선택한 논점을 다룬 다른 수집 자료를 찾아, 관련 구절과 읽을 이유를 알려 주세요.',
}
LABELS = {'explain': '이해하기', 'critique': '검토하기', 'related': '관련 자료'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS study_annotation_actions (
 id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL REFERENCES study_sessions(id),
 annotation_id INTEGER NOT NULL REFERENCES study_annotations(id), owner_key TEXT NOT NULL,
 intent TEXT NOT NULL CHECK(intent IN ('explain','critique','related')),
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL, prompt_version TEXT NOT NULL,
 parent_id INTEGER REFERENCES study_annotation_actions(id), retry_of INTEGER REFERENCES study_annotation_actions(id),
 question TEXT NOT NULL, context_json TEXT NOT NULL, conversation_id INTEGER,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','complete','error','cancelled')),
 result_json TEXT, error TEXT, claim_token TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now')), started_at TEXT, finished_at TEXT,
 UNIQUE(study_id, request_key)
);
CREATE INDEX IF NOT EXISTS study_actions_annotation ON study_annotation_actions(study_id, annotation_id, id);
CREATE INDEX IF NOT EXISTS study_actions_queue ON study_annotation_actions(owner_key, status, id);
CREATE UNIQUE INDEX IF NOT EXISTS study_actions_running ON study_annotation_actions(owner_key) WHERE status='running';
'''


def migrate(c):
    if 'intent' not in {r[1] for r in c.execute('PRAGMA table_info(study_annotations)')}:
        c.execute("ALTER TABLE study_annotations ADD COLUMN intent TEXT NOT NULL DEFAULT 'highlight'")
    c.executescript(SCHEMA)


def _owner(c, sid):
    s = study._session(c, sid)
    if s['project_id'] and not c.execute(
        'SELECT 1 FROM study_project_members WHERE project_id=? AND study_id=? AND removed_at IS NULL',
        (s['project_id'], sid),
    ).fetchone():
        raise HTTPException(409, '프로젝트에서 제거된 자료입니다. 다시 추가한 뒤 요청해 주세요.')
    return s, f"project:{s['project_id']}" if s['project_id'] else f'study:{sid}'


def _public(row):
    r = dict(row)
    context = json.loads(r.pop('context_json'))
    r['annotation_revision'] = context['annotations'][0]['revision']
    r['result'] = json.loads(r.pop('result_json') or 'null')
    r.pop('claim_token', None)
    r.pop('request_hash', None)
    return r


def list_actions(sid):
    c = get_connection()
    try:
        study._session(c, sid)
        return [_public(r) for r in c.execute('''SELECT a.*,
            (SELECT count(*) FROM study_annotation_actions b WHERE b.owner_key=a.owner_key
              AND b.status IN ('queued','running') AND b.id<=a.id) AS queue_position
            FROM study_annotation_actions a WHERE a.study_id=? ORDER BY a.id''', (sid,))]
    finally:
        c.close()


def queue_action(sid, body):
    c = get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        s, owner = _owner(c, sid)
        signature = hashlib.sha256(body.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
        old = c.execute('SELECT * FROM study_annotation_actions WHERE study_id=? AND request_key=?', (sid, body.request_key)).fetchone()
        if old:
            if old['request_hash'] != signature:
                raise HTTPException(409, '같은 요청 번호에 다른 내용이 있습니다. 새 요청으로 보내 주세요.')
            return {**_public(old), 'created': False}
        if c.execute("SELECT count(*) FROM study_annotation_actions WHERE owner_key=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 30:
            raise HTTPException(429, '대기 중인 요청이 30개입니다. 일부가 끝나면 다시 표시해 주세요.')
        if body.selection:
            sel = body.selection
            if not 0 <= sel.start < sel.end <= len(s['body']) or s['body'][sel.start:sel.end] != sel.exact:
                raise HTTPException(422, '선택 위치와 고정 원문이 일치하지 않습니다. 다시 선택해 주세요.')
            aid = c.execute('''INSERT INTO study_annotations(study_id,kind,intent,start_offset,end_offset,exact)
                VALUES(?,'highlight',?,?,?,?)''', (sid, body.intent, sel.start, sel.end, sel.exact)).lastrowid
            revision = 1
        else:
            aid, revision = body.annotation.id, body.annotation.revision
        question = body.question.strip() or QUESTIONS[body.intent]
        context = study._context(c, s, SimpleNamespace(action='question', question=question,
            annotations=[SimpleNamespace(id=aid, revision=revision)]))
        a = context['annotations'][0]
        if s['body'][a['start_offset']:a['end_offset']] != a['exact']:
            raise HTTPException(409, '표시와 고정 원문이 일치하지 않습니다.')
        # A wider, bounded passage plus section headings resolves short/ambiguous selections.
        start, end = max(0, a['start_offset']-2400), min(len(s['body']), a['end_offset']+2400)
        headings = re.findall(r'^#{1,6}\s+(.+)$', s['body'][:a['start_offset']], re.M)[-3:]
        passage = s['body'][start:end]
        context.update(study_intent=body.intent, prompt_version=PROMPT_VERSION, project_id=s['project_id'],
            document_id=s['document_id'], title=s['title'], published_at=s['published_at'],
            research_mode=body.research, passage={'start': start, 'end': end, 'text': passage, 'headings': headings})
        href = f"/study/projects/{s['project_id']}?doc={sid}&annotation={aid}" if s['project_id'] else f'/study/{sid}?annotation={aid}'
        context['evidence'][0].update(href=href, text=context['evidence'][0]['text']+
            '\n[문서 소제목]\n'+' / '.join(headings)+'\n[인접 본문 · 읽은 범위]\n'+passage)
        parent_id = body.parent_id
        retry_of = body.retry_of
        if retry_of:
            old = c.execute('SELECT * FROM study_annotation_actions WHERE id=? AND study_id=? AND annotation_id=?', (retry_of, sid, aid)).fetchone()
            if not old or old['status'] not in ('error', 'cancelled') or old['intent'] != body.intent:
                raise HTTPException(409, '실패하거나 취소된 같은 표시의 작업만 재시도할 수 있습니다.')
            # Retry the frozen input, even when the user's note has since changed.
            context = json.loads(old['context_json'])
            question, parent_id = old['question'], old['parent_id']
        elif parent_id:
            parent = c.execute("SELECT * FROM study_annotation_actions WHERE id=? AND study_id=? AND annotation_id=? AND status='complete'", (parent_id, sid, aid)).fetchone()
            if not parent or parent['intent'] != body.intent:
                raise HTTPException(409, '이 표시의 완료된 답변을 선택해 이어서 질문해 주세요.')
            prior = json.loads(parent['context_json'])
            result = json.loads(parent['result_json'])
            chain = prior.get('followup_chain', []) + [{'question': parent['question'], 'answer': result['answer']}]
            # Keep explicit ancestors only, bounded independently of unrelated global chat.
            context['followup_chain'] = chain[-4:]
        tid = c.execute('''INSERT INTO study_annotation_actions(study_id,annotation_id,owner_key,intent,
            request_key,request_hash,prompt_version,parent_id,retry_of,question,context_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (sid, aid, owner, body.intent, body.request_key, signature,
            context['prompt_version'], parent_id, retry_of, question, json.dumps(context, ensure_ascii=False))).lastrowid
        c.execute("UPDATE study_sessions SET updated_at=datetime('now') WHERE id=?", (sid,))
        c.commit()
        return {**_public(c.execute('SELECT * FROM study_annotation_actions WHERE id=?', (tid,)).fetchone()), 'created': True}
    finally:
        c.close()


def _claim(owner):
    c = get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM study_annotation_actions WHERE owner_key=? AND status='running'", (owner,)).fetchone():
            return None
        while True:
            row = c.execute("SELECT * FROM study_annotation_actions WHERE owner_key=? AND status='queued' ORDER BY id LIMIT 1", (owner,)).fetchone()
            if not row:
                c.commit()
                return None
            r = dict(row)
            a = c.execute('SELECT deleted_at FROM study_annotations WHERE id=?', (r['annotation_id'],)).fetchone()
            try:
                _owner(c, r['study_id'])
                valid = a and not a['deleted_at']
            except HTTPException:
                valid = False
            if valid:
                break
            c.execute("UPDATE study_annotation_actions SET status='cancelled',finished_at=datetime('now'),error=? WHERE id=?", ('표시가 삭제되거나 프로젝트에서 자료가 제거되어 취소했습니다.', r['id']))
        context = json.loads(r['context_json'])
        cid = c.execute("INSERT INTO conversations(channel,title,state_json) VALUES('web',?,'{}')", ('스터디 · '+context['title'][:70]+' · '+LABELS[r['intent']],)).lastrowid
        for pair in context.get('followup_chain', []):
            for role, content in [('user', pair['question']), ('assistant', pair['answer'])]:
                c.execute('INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,?,?)', (cid, role, content[:6000]))
        c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'user',?)", (cid, r['question']))
        token = uuid.uuid4().hex
        c.execute("UPDATE study_annotation_actions SET status='running',conversation_id=?,claim_token=?,started_at=datetime('now') WHERE id=?", (cid, token, r['id']))
        c.commit()
        return {**r, 'conversation_id': cid, 'claim_token': token}
    finally:
        c.close()


def drain(owner):
    """Every admission schedules a drain; the database serializes workers per owner."""
    from pipeline.chat import generate_answer
    while (r := _claim(owner)) is not None:
        context = json.loads(r['context_json'])
        try:
            result = generate_answer(r['conversation_id'], r['question'], study_context=context)
            if not result.get('answer') and not result.get('error'):
                result['error'] = 'AI 답변이 비어 있습니다. 다시 시도해 주세요.'
        except Exception:
            result = {'error': '답변 생성에 실패했습니다. 표시는 저장되어 있습니다.'}
        result['research'] = context.get('research')
        c = get_connection()
        try:
            if result.get('error'):
                last = c.execute('SELECT role FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1', (r['conversation_id'],)).fetchone()
                if last and last['role'] == 'user':
                    c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'assistant',?)", (r['conversation_id'], result['error']))
            c.execute("""UPDATE study_annotation_actions SET status=?,error=?,result_json=?,finished_at=datetime('now')
                WHERE id=? AND status='running' AND claim_token=?""", ('error' if result.get('error') else 'complete',
                result.get('error'), json.dumps(result, ensure_ascii=False), r['id'], r['claim_token']))
            c.commit()
        finally:
            c.close()


def cancel(sid, aid):
    c = get_connection()
    try:
        cur = c.execute("UPDATE study_annotation_actions SET status='cancelled',finished_at=datetime('now') WHERE id=? AND study_id=? AND status='queued'", (aid, sid))
        if not cur.rowcount:
            raise HTTPException(409, '대기 중인 요청만 취소할 수 있습니다.')
        c.commit()
        return {'ok': True}
    finally:
        c.close()


def recover(sid, aid):
    c = get_connection()
    try:
        cur = c.execute("""UPDATE study_annotation_actions SET status='error',claim_token=NULL,
            error='실행이 중단됐습니다. 다시 시도해 주세요.',finished_at=datetime('now')
            WHERE id=? AND study_id=? AND status='running' AND started_at<=datetime('now','-10 minutes')""", (aid, sid))
        if not cur.rowcount:
            raise HTTPException(409, '10분 이상 멈춘 실행만 정리할 수 있습니다.')
        c.commit()
        return {'ok': True}
    finally:
        c.close()


def owner_for(sid):
    c = get_connection()
    try:
        return _owner(c, sid)[1]
    finally:
        c.close()

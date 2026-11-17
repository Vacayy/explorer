"""Transactional admission and completion for isolated study conversations."""
import json
from fastapi import HTTPException
from psycopg.rows import dict_row
from pipeline import study, study_projects, study_coach
from pipeline.postgres_graph_fixture import _guard
from pipeline import postgres_study_owners as owners
from pipeline.postgres_chat_generation import generate_answer

NOW = "to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')"


class _QuestionReader:
    """Adapt the existing read-only study context builders to a PG cursor."""
    def __init__(self, cursor): self.cursor = cursor
    def execute(self, query, params=()):
        # Only called by the fixed, internal context/prepare queries.
        self.cursor.execute(query.replace('?', '%s'), params)
        return self.cursor


class StudyTurnsFixture:
    def __init__(self, connect, chat_store, tools, *, owner_chat_id=None):
        self.connect, self.chat_store, self.tools = connect, chat_store, tools
        self.owner_chat_id = owner_chat_id

    def queue(self, owner_id, body, *, project=False):
        table, key, owner_table = (('study_project_turns','project_id','study_projects') if project
                                    else ('study_turns','study_id','study_sessions'))
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute(f'SELECT * FROM {owner_table} WHERE id=%s FOR UPDATE', (owner_id,))
                owner = cur.fetchone()
                if not owner:
                    raise HTTPException(404, '스터디를 찾을 수 없습니다')
                cur.execute(f'SELECT id,conversation_id FROM {table} WHERE {key}=%s AND request_key=%s', (owner_id,body.request_key))
                old = cur.fetchone()
                if old:
                    return {**old,'created':False}
                if cur.execute(f"SELECT 1 FROM {table} WHERE {key}=%s AND status='pending'", (owner_id,)).fetchone():
                    raise HTTPException(409,'이전 답변을 생성 중입니다. 완료 후 질문해 주세요.')
                if not body.question.strip() and (project or body.action == 'question'):
                    raise HTTPException(422,'질문을 입력해 주세요.')
                reader = _QuestionReader(cur)
                continuing = getattr(body,'context_mode','auto') == 'continue'
                if project:
                    context = {'project_id':owner_id,'study_id':None} if continuing else study_projects._context(reader,owner_id,body)
                else:
                    context = {'study_id':owner_id} if continuing else study._context(reader,owner,body)
                context = study_coach.prepare(reader,table,key,owner_id,body,context)
                question = body.question.strip() or '선택한 하이라이트의 핵심을 요약하고 서로 연결되는 내용을 설명해 주세요.'
                cid = owner['conversation_id']
                cur.execute('SELECT 1 FROM conversations WHERE id=%s', (cid,))
                if cid is None or not cur.fetchone():
                    label = ('스터디 프로젝트 · ' if project else '스터디 · ') + owner['title'][:80 if project else 90]
                    member = (owners.project_owner if project else owners.session_owner)(c, owner_id)
                    channel, chat = owners.conversation_of(member, self.owner_chat_id)
                    cur.execute("INSERT INTO conversations(channel,title,state_json,chat_id) VALUES(%s,%s,'{}',%s) RETURNING id", (channel,label,chat))
                    cid = cur.fetchone()['id']
                cur.execute('SELECT role FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1', (cid,))
                last = cur.fetchone()
                if last and last['role'] == 'user':
                    raise HTTPException(409,'이 대화에 답변 생성 중인 질문이 있습니다.')
                cur.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,'user',%s) RETURNING id", (cid,question))
                mid = cur.fetchone()['id']
                cur.execute(f'''INSERT INTO {table}({key},conversation_id,message_id,request_key,question,context_json,status,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,'pending',{NOW}) RETURNING id''',
                    (owner_id,cid,mid,body.request_key,question,json.dumps(context,ensure_ascii=False)))
                tid=cur.fetchone()['id']
                cur.execute(f'UPDATE {owner_table} SET conversation_id=%s,updated_at={NOW} WHERE id=%s',(cid,owner_id))
                cur.execute(f'UPDATE conversations SET updated_at={NOW} WHERE id=%s',(cid,))
                return {'id':tid,'conversation_id':cid,'created':True}

    def execute(self, turn_id, *, project=False):
        table = 'study_project_turns' if project else 'study_turns'
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                lock_key = f'{table}:{turn_id}'
                cur.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired', (lock_key,))
                if not cur.fetchone()['acquired']:
                    return
                cur.execute(f'SELECT * FROM {table} WHERE id=%s',(turn_id,))
                row=cur.fetchone()
                if not row or row['status'] != 'pending':
                    return
                # A previously committed answer means the external call may have
                # succeeded before this worker died. Never call it again here.
                cur.execute('SELECT id,role FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1', (row['conversation_id'],))
                last=cur.fetchone()
                if not last or last['id'] != row['message_id'] or last['role'] != 'user':
                    return
                context=json.loads(row['context_json'])
                result=generate_answer(self.chat_store,self.tools,row['conversation_id'],row['question'],
                                       owner_chat_id=owners.chat_owner(c,row['conversation_id'],self.owner_chat_id),study_context=context)
                cur.execute(f"UPDATE {table} SET status=%s,error=%s,context_json=%s,finished_at={NOW} WHERE id=%s AND status='pending'",
                    ('error' if result.get('error') else 'complete',result.get('error'),json.dumps(context,ensure_ascii=False),turn_id))

    def recover(self, owner_id, turn_id, *, project=False):
        table, key, owner_table = (('study_project_turns','project_id','study_projects') if project
                                    else ('study_turns','study_id','study_sessions'))
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute(f'SELECT id FROM {owner_table} WHERE id=%s FOR UPDATE', (owner_id,))
                if not cur.fetchone():
                    raise HTTPException(404,'스터디를 찾을 수 없습니다')
                cur.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired', (f'{table}:{turn_id}',))
                if not cur.fetchone()['acquired']:
                    raise HTTPException(409,'답변 생성이 진행 중입니다. 잠시 후 다시 확인해 주세요.')
                cur.execute(f"""SELECT *, (extract(epoch from (timezone('utc',now()) - created_at::timestamp))) AS age
                    FROM {table} WHERE id=%s AND {key}=%s FOR UPDATE""", (turn_id,owner_id))
                row=cur.fetchone()
                if not row or row['status'] != 'pending' or row['age'] is None or row['age'] < 600:
                    raise HTTPException(409,'10분 이상 멈춘 요청만 정리할 수 있습니다.')
                cur.execute('SELECT id,role FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1', (row['conversation_id'],))
                last=cur.fetchone()
                if last and last['id'] == row['message_id'] and last['role'] == 'user':
                    message='스터디 답변 요청이 중단됐습니다. 같은 내용을 다시 보내 주세요.'
                    cur.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,'assistant',%s)", (row['conversation_id'],message))
                else:
                    # A stored answer is retained; whether the model call fully
                    # finished cannot be inferred from a bare assistant row.
                    message='저장된 대화는 보존했지만 요청의 완료 상태를 확인하지 못했습니다.'
                cur.execute(f"UPDATE {table} SET status='error',error=%s,finished_at={NOW} WHERE id=%s AND status='pending'", (message,turn_id))
                return {'ok':True}

"""Read preserved annotation actions in a disposable study candidate."""
from fastapi import HTTPException
from psycopg.rows import dict_row
from pipeline.postgres_graph_fixture import _guard
from pipeline.study_actions import _public


class StudyActionsFixture:
    def __init__(self, connect, chat_store=None, tools=None, *, owner_chat_id=None):
        self.connect, self.chat_store, self.tools = connect, chat_store, tools
        self.owner_chat_id = owner_chat_id

    def listing(self, study_id):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                if not cur.execute('SELECT 1 FROM study_sessions WHERE id=%s',(study_id,)).fetchone():
                    raise HTTPException(404,'스터디를 찾을 수 없습니다')
                cur.execute('''SELECT a.*,
                    (SELECT count(*) FROM study_annotation_actions b WHERE b.owner_key=a.owner_key
                     AND b.status IN ('queued','running') AND b.id<=a.id) AS queue_position
                    FROM study_annotation_actions a WHERE a.study_id=%s ORDER BY a.id''',(study_id,))
                return [_public(row) for row in cur.fetchall()]

    @staticmethod
    def _owner(cur, sid, *, lock=False):
        cur.execute('SELECT * FROM study_sessions WHERE id=%s'+(' FOR UPDATE' if lock else ''),(sid,))
        session=cur.fetchone()
        if not session: raise HTTPException(404,'스터디를 찾을 수 없습니다')
        if session['project_id']:
            cur.execute('SELECT 1 FROM study_project_members WHERE project_id=%s AND study_id=%s AND removed_at IS NULL',(session['project_id'],sid))
            if not cur.fetchone():raise HTTPException(409,'프로젝트에서 제거된 자료입니다. 다시 추가한 뒤 요청해 주세요.')
        return session, f"project:{session['project_id']}" if session['project_id'] else f'study:{sid}'

    def queue(self, sid, body):
        import hashlib,json,re
        from types import SimpleNamespace
        from pipeline import study
        from pipeline.study_actions import PROMPT_VERSION,QUESTIONS
        from pipeline.postgres_study_turn_fixture import _QuestionReader,NOW
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                session,owner=self._owner(cur,sid,lock=True)
                # Shared projects must serialize requests across their studies.
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))',(owner,))
                signature=hashlib.sha256(body.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
                cur.execute('SELECT * FROM study_annotation_actions WHERE study_id=%s AND request_key=%s',(sid,body.request_key))
                old=cur.fetchone()
                if old:
                    if old['request_hash']!=signature:raise HTTPException(409,'같은 요청 번호에 다른 내용이 있습니다. 새 요청으로 보내 주세요.')
                    return {**_public(old),'created':False}
                cur.execute("SELECT count(*) AS n FROM study_annotation_actions WHERE owner_key=%s AND status IN ('queued','running')",(owner,))
                if cur.fetchone()['n']>=30:raise HTTPException(429,'대기 중인 요청이 30개입니다. 일부가 끝나면 다시 표시해 주세요.')
                if body.selection:
                    sel=body.selection
                    if not 0<=sel.start<sel.end<=len(session['body']) or session['body'][sel.start:sel.end]!=sel.exact:
                        raise HTTPException(422,'선택 위치와 고정 원문이 일치하지 않습니다. 다시 선택해 주세요.')
                    cur.execute(f"""INSERT INTO study_annotations(study_id,kind,intent,start_offset,end_offset,exact,comment,revision,created_at,updated_at)
                        VALUES(%s,'highlight',%s,%s,%s,%s,'',1,{NOW},{NOW}) RETURNING id""",(sid,body.intent,sel.start,sel.end,sel.exact))
                    aid,revision=cur.fetchone()['id'],1
                else:aid,revision=body.annotation.id,body.annotation.revision
                question=body.question.strip() or QUESTIONS[body.intent]
                context=study._context(_QuestionReader(cur),session,SimpleNamespace(action='question',question=question,annotations=[SimpleNamespace(id=aid,revision=revision)]))
                annotation=context['annotations'][0]
                if session['body'][annotation['start_offset']:annotation['end_offset']]!=annotation['exact']:
                    raise HTTPException(409,'표시와 고정 원문이 일치하지 않습니다.')
                start,end=max(0,annotation['start_offset']-2400),min(len(session['body']),annotation['end_offset']+2400)
                headings=re.findall(r'^#{1,6}\s+(.+)$',session['body'][:annotation['start_offset']],re.M)[-3:]
                passage=session['body'][start:end]
                context.update(study_intent=body.intent,prompt_version=PROMPT_VERSION,project_id=session['project_id'],document_id=session['document_id'],title=session['title'],published_at=session['published_at'],research_mode=body.research,passage={'start':start,'end':end,'text':passage,'headings':headings})
                href=f"/study/projects/{session['project_id']}?doc={sid}&annotation={aid}" if session['project_id'] else f'/study/{sid}?annotation={aid}'
                context['evidence'][0].update(href=href,text=context['evidence'][0]['text']+'\n[문서 소제목]\n'+' / '.join(headings)+'\n[인접 본문 · 읽은 범위]\n'+passage)
                parent_id,retry_of=body.parent_id,body.retry_of
                if retry_of:
                    cur.execute('SELECT * FROM study_annotation_actions WHERE id=%s AND study_id=%s AND annotation_id=%s',(retry_of,sid,aid));old=cur.fetchone()
                    if not old or old['status'] not in ('error','cancelled') or old['intent']!=body.intent:raise HTTPException(409,'실패하거나 취소된 같은 표시의 작업만 재시도할 수 있습니다.')
                    context=json.loads(old['context_json']);question,parent_id=old['question'],old['parent_id']
                elif parent_id:
                    cur.execute("SELECT * FROM study_annotation_actions WHERE id=%s AND study_id=%s AND annotation_id=%s AND status='complete'",(parent_id,sid,aid));parent=cur.fetchone()
                    if not parent or parent['intent']!=body.intent:raise HTTPException(409,'이 표시의 완료된 답변을 선택해 이어서 질문해 주세요.')
                    prior=json.loads(parent['context_json']);result=json.loads(parent['result_json'])
                    context['followup_chain']=(prior.get('followup_chain',[])+[{'question':parent['question'],'answer':result['answer']}])[-4:]
                cur.execute(f'''INSERT INTO study_annotation_actions(study_id,annotation_id,owner_key,intent,request_key,request_hash,prompt_version,parent_id,retry_of,question,context_json,status,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',{NOW}) RETURNING *''',
                    (sid,aid,owner,body.intent,body.request_key,signature,context['prompt_version'],parent_id,retry_of,question,json.dumps(context,ensure_ascii=False)))
                result=cur.fetchone();cur.execute(f'UPDATE study_sessions SET updated_at={NOW} WHERE id=%s',(sid,))
                return {**_public(result),'created':True}

    def drain(self, owner):
        """One worker per owner. Existing running work is never replayed."""
        import json,uuid
        from pipeline.study_actions import LABELS
        from pipeline.postgres_chat_generation import generate_answer
        from pipeline.postgres_study_turn_fixture import NOW
        with self.connect() as guard:
            _guard(guard)
            if not guard.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,2))',(owner,)).fetchone()[0]:return
            while True:
                with self.connect() as c:
                    _guard(c)
                    with c.cursor(row_factory=dict_row) as cur:
                        cur.execute("SELECT 1 FROM study_annotation_actions WHERE owner_key=%s AND status='running'",(owner,))
                        if cur.fetchone():return
                        cur.execute("SELECT * FROM study_annotation_actions WHERE owner_key=%s AND status='queued' ORDER BY id LIMIT 1 FOR UPDATE",(owner,))
                        row=cur.fetchone()
                        if not row:return
                        try:
                            self._owner(cur,row['study_id'])
                            cur.execute('SELECT deleted_at FROM study_annotations WHERE id=%s',(row['annotation_id'],));annotation=cur.fetchone()
                            valid=bool(annotation and not annotation['deleted_at'])
                        except HTTPException:valid=False
                        if not valid:
                            cur.execute(f"UPDATE study_annotation_actions SET status='cancelled',error=%s,finished_at={NOW} WHERE id=%s",('표시가 삭제되거나 프로젝트에서 자료가 제거되어 취소했습니다.',row['id']))
                            continue
                        context=json.loads(row['context_json'])
                        cur.execute("INSERT INTO conversations(channel,title,state_json,chat_id) VALUES('web',%s,'{}',%s) RETURNING id",('스터디 · '+context['title'][:70]+' · '+LABELS[row['intent']],self.owner_chat_id));cid=cur.fetchone()['id']
                        for pair in context.get('followup_chain',[]):
                            for role,content in (('user',pair['question']),('assistant',pair['answer'])):
                                cur.execute('INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,%s,%s)',(cid,role,content[:6000]))
                        cur.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,'user',%s)",(cid,row['question']))
                        token=uuid.uuid4().hex
                        cur.execute(f"UPDATE study_annotation_actions SET status='running',conversation_id=%s,claim_token=%s,started_at={NOW} WHERE id=%s",(cid,token,row['id']))
                try:
                    result=generate_answer(self.chat_store,self.tools,cid,row['question'],owner_chat_id=self.owner_chat_id,study_context=context)
                    if not result.get('answer') and not result.get('error'):result['error']='AI 답변이 비어 있습니다. 다시 시도해 주세요.'
                except Exception:result={'error':'답변 생성에 실패했습니다. 표시는 저장되어 있습니다.'}
                result['research']=context.get('research')
                with self.connect() as c:
                    _guard(c)
                    if result.get('error'):
                        last=c.execute('SELECT role FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
                        if last and last[0]=='user':c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,'assistant',%s)",(cid,result['error']))
                    c.execute(f"""UPDATE study_annotation_actions SET status=%s,error=%s,result_json=%s,finished_at={NOW}
                        WHERE id=%s AND status='running' AND claim_token=%s""",('error' if result.get('error') else 'complete',result.get('error'),json.dumps(result,ensure_ascii=False),row['id'],token))

    def cancel(self,sid,aid):
        from pipeline.postgres_study_turn_fixture import NOW
        with self.connect() as c:
            _guard(c)
            result=c.execute(f"UPDATE study_annotation_actions SET status='cancelled',finished_at={NOW} WHERE id=%s AND study_id=%s AND status='queued'",(aid,sid))
            if not result.rowcount:raise HTTPException(409,'대기 중인 요청만 취소할 수 있습니다.')
            return {'ok':True}

    def owner_for(self,sid):
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:return self._owner(cur,sid)[1]

    def recover(self,sid,aid):
        from pipeline.postgres_study_turn_fixture import NOW
        with self.connect() as c:
            _guard(c)
            with c.cursor(row_factory=dict_row) as cur:
                _,owner=self._owner(cur,sid)
                cur.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,2)) AS acquired',(owner,))
                if not cur.fetchone()['acquired']:raise HTTPException(409,'답변 생성이 진행 중입니다.')
                cur.execute(f"""UPDATE study_annotation_actions SET status='error',claim_token=NULL,
                    error='실행이 중단됐습니다. 다시 시도해 주세요.',finished_at={NOW}
                    WHERE id=%s AND study_id=%s AND status='running' AND started_at::timestamp<=timezone('utc',now())-interval '10 minutes'""",(aid,sid))
                if not cur.rowcount:raise HTTPException(409,'10분 이상 멈춘 실행만 정리할 수 있습니다.')
                return {'ok':True}

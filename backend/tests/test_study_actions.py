import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from models.study_actions import AnnotationActionRequest
from pipeline import study, study_actions as actions, study_intents as intents, study_projects, chat
from routers.spine_study import EditAnnotation, router


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class StudyActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'study.db'
        for module in (study, actions, intents):
            p = patch.object(module, 'get_connection', side_effect=self.connect)
            p.start(); self.addCleanup(p.stop)
        with self.connect() as c:
            c.executescript(study.SCHEMA + study_projects.SCHEMA + '''
                CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source_type TEXT,published_at TEXT,markdown TEXT,raw_content TEXT);
                CREATE TABLE conversations(id INTEGER PRIMARY KEY,channel TEXT,title TEXT,state_json TEXT,updated_at TEXT);
                CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT);
                INSERT INTO raw_documents VALUES(1,'금리와 기업','https://example.com/1','blog','2026-09-10',NULL,'가😀나다. 다음 문장.');
                INSERT INTO raw_documents VALUES(2,'다른 글','https://example.com/2','telegram','2026-09-10',NULL,'다른 내용');
            ''')
            actions.migrate(c)
        self.sid = study.open_document(1)['id']

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def request(self, key='intent-001', **extra):
        return AnnotationActionRequest(**{'intent': 'explain', 'request_key': key,
            'selection': {'start': 1, 'end': 3, 'exact': '😀나'}, **extra})

    def record(self, action_id):
        with self.connect() as c:
            return dict(c.execute('SELECT * FROM study_annotation_actions WHERE id=?', (action_id,)).fetchone())

    def test_migration_preserves_old_annotations_and_is_repeatable(self):
        with self.connect() as c:
            c.execute("INSERT INTO study_annotations(study_id,kind,start_offset,end_offset,exact) VALUES(?,'highlight',0,1,'가')", (self.sid,))
            actions.migrate(c); actions.migrate(c)
            self.assertEqual(c.execute('SELECT intent,revision,exact FROM study_annotations').fetchone()[:], ('highlight', 1, '가'))

    def test_atomic_unicode_selection_idempotency_and_conflicting_keys(self):
        with ThreadPoolExecutor(2) as pool:
            first, second = list(pool.map(lambda _: actions.queue_action(self.sid, self.request()), range(2)))
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(sum(r['created'] for r in [first, second]), 1)
        self.assertEqual(len(study.read_study(self.sid)['annotations']), 1)
        with self.assertRaises(HTTPException):
            actions.queue_action(self.sid, self.request(intent='critique'))
        with self.assertRaises(HTTPException):
            actions.queue_action(self.sid, self.request('bad-offset', selection={'start': 1, 'end': 2, 'exact': '😀나'}))
        self.assertEqual(len(study.read_study(self.sid)['annotations']), 1)

    def test_snapshot_revision_membership_and_failed_transaction(self):
        a = actions.queue_action(self.sid, self.request())
        ref = {'id': a['annotation_id'], 'revision': 1}
        study.edit_annotation(self.sid, ref['id'], EditAnnotation(revision=1, comment='새로운 생각'))
        frozen = json.loads(self.record(a['id'])['context_json'])
        self.assertEqual(frozen['annotations'][0]['comment'], '')
        self.assertEqual(frozen['passage']['text'], '가😀나다. 다음 문장.')
        self.assertEqual(frozen['study_intent'], 'explain')
        with self.assertRaises(HTTPException):
            actions.queue_action(self.sid, self.request('stale-ref', selection=None, annotation=ref))
        with self.assertRaises(HTTPException):
            actions.queue_action(study.open_document(2)['id'], self.request('foreign-ref', selection=None, annotation=ref))
        # An invalid parent must roll back the entire admission.
        before = len(actions.list_actions(self.sid))
        with self.assertRaises(HTTPException):
            actions.queue_action(self.sid, self.request('bad-parent', selection=None, annotation={**ref, 'revision': 2}, parent_id=999, question='왜?'))
        self.assertEqual(len(actions.list_actions(self.sid)), before)

    def test_fifo_claim_is_single_worker_and_failure_does_not_block_next(self):
        first = actions.queue_action(self.sid, self.request())
        second = actions.queue_action(self.sid, self.request('intent-002', intent='critique'))
        entered, release = threading.Event(), threading.Event()
        calls = []
        def answer(cid, question, study_context):
            calls.append(study_context['study_intent'])
            if len(calls) == 1:
                entered.set(); release.wait(5)
                raise RuntimeError('model unavailable')
            return {'answer': '조건부 타당합니다.', 'citations': []}
        with patch.object(chat, 'generate_answer', side_effect=answer), ThreadPoolExecutor(2) as pool:
            worker = pool.submit(actions.drain, first['owner_key'])
            self.assertTrue(entered.wait(3))
            pool.submit(actions.drain, first['owner_key']).result(timeout=3)
            self.assertEqual(calls, ['explain'])
            release.set(); worker.result(timeout=5)
        self.assertEqual(calls, ['explain', 'critique'])
        self.assertEqual(self.record(first['id'])['status'], 'error')
        self.assertEqual(self.record(second['id'])['status'], 'complete')

    def test_followup_branches_only_from_selected_answer_and_retry_keeps_input(self):
        a = actions.queue_action(self.sid, self.request())
        with patch.object(chat, 'generate_answer', return_value={'answer': '금리란 자금의 가격입니다.', 'citations': []}):
            actions.drain(a['owner_key'])
        other = actions.queue_action(self.sid, self.request('unrelated', intent='related', selection={'start': 6, 'end': 8, 'exact': '다음'}))
        with patch.object(chat, 'generate_answer', return_value={'answer': '섞이면 안 되는 다른 답변', 'citations': []}):
            actions.drain(a['owner_key'])
        follow = actions.queue_action(self.sid, self.request('follow-up', selection=None,
            annotation={'id': a['annotation_id'], 'revision': 1}, parent_id=a['id'], question='이 경우는요?'))
        captured = []
        def answer(cid, question, study_context):
            with self.connect() as c:
                captured.extend(r['content'] for r in c.execute('SELECT content FROM chat_messages WHERE conversation_id=?', (cid,)))
            study_context['research'] = {'results': []}
            return {'error': '실패'}
        with patch.object(chat, 'generate_answer', side_effect=answer):
            actions.drain(a['owner_key'])
        self.assertIn('금리란 자금의 가격입니다.', captured)
        self.assertNotIn('섞이면 안 되는 다른 답변', captured)
        with self.assertRaises(HTTPException):
            actions.queue_action(self.sid, self.request('wrong-parent', selection=None,
                annotation={'id': a['annotation_id'], 'revision': 1}, parent_id=other['id'], question='왜?'))
        study.edit_annotation(self.sid, a['annotation_id'], EditAnnotation(revision=1, comment='후에 작성'))
        retry = actions.queue_action(self.sid, self.request('retry-001', selection=None,
            annotation={'id': a['annotation_id'], 'revision': 2}, retry_of=follow['id']))
        self.assertEqual(self.record(follow['id'])['context_json'], self.record(retry['id'])['context_json'])
        self.assertEqual(retry['parent_id'], a['id'])

    def test_queue_cancel_deleted_mark_and_stale_worker_fencing(self):
        a = actions.queue_action(self.sid, self.request())
        b = actions.queue_action(self.sid, self.request('cancel-me'))
        actions.cancel(self.sid, b['id'])
        claimed = actions._claim(a['owner_key'])
        with self.assertRaises(HTTPException): actions.cancel(self.sid, a['id'])
        with self.assertRaises(HTTPException): actions.recover(self.sid, a['id'])
        with self.connect() as c:
            c.execute("UPDATE study_annotation_actions SET started_at=datetime('now','-11 minutes') WHERE id=?", (a['id'],))
        actions.recover(self.sid, a['id'])
        self.assertNotEqual(claimed['claim_token'], self.record(a['id'])['claim_token'])
        d = actions.queue_action(self.sid, self.request('deleted-mark'))
        study.edit_annotation(self.sid, d['annotation_id'], EditAnnotation(revision=1, delete=True))
        self.assertIsNone(actions._claim(a['owner_key']))
        self.assertEqual(self.record(d['id'])['status'], 'cancelled')

    def test_project_documents_share_queue_and_removed_member_rejected(self):
        with self.connect() as c:
            pid = c.execute("INSERT INTO study_projects(title) VALUES('매크로 공부')").lastrowid
        ids = [study.open_document(doc, project_id=pid)['id'] for doc in (1, 2)]
        with self.connect() as c:
            c.executemany('INSERT INTO study_project_members(project_id,study_id) VALUES(?,?)', [(pid, sid) for sid in ids])
        a = actions.queue_action(ids[0], self.request())
        b = actions.queue_action(ids[1], self.request(selection={'start': 0, 'end': 2, 'exact': '다른'}))
        self.assertEqual(a['owner_key'], b['owner_key'])
        self.assertEqual(actions.list_actions(ids[1])[0]['queue_position'], 2)
        self.assertIn('/study/projects/', json.loads(self.record(a['id'])['context_json'])['evidence'][0]['href'])
        with self.connect() as c:
            c.execute("UPDATE study_project_members SET removed_at=datetime('now') WHERE study_id=?", (ids[1],))
        with self.assertRaises(HTTPException):
            actions.queue_action(ids[1], self.request('removed-1', selection={'start': 0, 'end': 2, 'exact': '다른'}))

    def test_library_excludes_original_and_exact_reposts(self):
        a = actions.queue_action(self.sid, self.request(intent='related'))
        context = json.loads(self.record(a['id'])['context_json'])
        with self.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES(3,'원문 재전파','https://example.com/3','blog',NULL,NULL,'가😀나다.  다음 문장.')")
            c.execute("INSERT INTO raw_documents VALUES(4,'다른 글 재전파','https://example.com/4','blog',NULL,NULL,'다른 내용')")
        items = [{'doc_id': i, 'href': f'/doc/{i}', 'text': '관련 발췌', 'title': f'자료 {i}'} for i in range(1, 5)]
        result = intents._library_items(items, context, set())
        self.assertEqual([e['doc_id'] for e in result], [2])
        self.assertEqual(result[0]['read_scope'], '검색 발췌')

    def test_explicit_intent_bypasses_keyword_router_and_web_is_opt_in_for_related(self):
        a = actions.queue_action(self.sid, self.request(intent='related'))
        context = json.loads(self.record(a['id'])['context_json'])
        response = SimpleNamespace(text='{"library_queries":["금리"],"web_query":"미국 금리"}')
        with patch.object(intents.llm, 'run', return_value=response):
            decision = intents.plan(context, '검증해 줘')
        self.assertIsNone(decision['web_query'])
        turn = SimpleNamespace(evidence=[], route={}, question='검증해 줘', tool_log=[])
        with patch.object(intents, 'plan', return_value=decision), patch('pipeline.chat_tools.search_docs', return_value=SimpleNamespace(items=[], note='검색 결과 없음')):
            intents.augment(turn, context, lambda _: None)
        self.assertEqual(turn.route['study_task'], 'related')
        self.assertEqual(context['research']['notes'], ['검색 결과 없음'])

    def test_http_read_is_inert_and_post_background_runs_once(self):
        app = FastAPI(); app.include_router(router)
        client = TestClient(app)
        with patch.object(chat, 'generate_answer', return_value={'answer': '문맥 설명', 'citations': []}) as model:
            payload = self.request().model_dump()
            first = client.post(f'/api/spine/studies/{self.sid}/actions', json=payload)
            self.assertEqual(first.status_code, 200)
            second = client.post(f'/api/spine/studies/{self.sid}/actions', json=payload)
            self.assertEqual(second.json()['id'], first.json()['id'])
            self.assertEqual(client.get(f'/api/spine/studies/{self.sid}/actions').json()[0]['status'], 'complete')
            self.assertEqual(model.call_count, 1)


if __name__ == '__main__':
    unittest.main()

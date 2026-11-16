"""Disposable PG study transfer and annotation behavior."""
from types import SimpleNamespace
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from routers.postgres_study_fixture import create_router
from pipeline import study, study_actions, study_projects
from pipeline.postgres_chat_preview_fork import fork_chat_preview
from pipeline.postgres_study_fixture import import_studies, StudyFixture
from tests.test_postgres_chat_preview_fork import ChatPreviewForkTests


class StudyFixtureTests(ChatPreviewForkTests):
    def setUp(self):
        super().setUp()
        self.source.rollback()
        self.source.execute('PRAGMA query_only=OFF')
        self.source.executescript(study.SCHEMA + study_projects.SCHEMA + study_actions.SCHEMA)
        self.source.execute("ALTER TABLE study_annotations ADD COLUMN intent TEXT NOT NULL DEFAULT 'highlight'")
        self.source.execute("INSERT INTO study_sessions(id,document_id,title,body_kind,body,content_hash) VALUES(4,1,'자료','원문','한글😀문장','hash')")
        self.source.execute("INSERT INTO study_annotations(id,study_id,kind,start_offset,end_offset,exact) VALUES(8,4,'highlight',2,3,'😀')")
        self.source.commit()
        self.source.execute('PRAGMA query_only=ON')
        self.source.execute('BEGIN')

    def test_import_and_annotation_lifecycle(self):
        with self.target() as pg:
            fork_chat_preview(self.source, pg, self.fixture.schema)
            counts = import_studies(self.source, pg)
            self.assertEqual(counts['study_sessions'], 1)
            self.assertEqual(counts['study_annotations'], 1)
        store = StudyFixture(self.target)
        self.assertEqual(store.read(4)['annotations'][0]['exact'], '😀')
        new = store.add_annotation(4, SimpleNamespace(kind='comment', start=2, end=3, exact='😀', comment='메모'))
        self.assertGreater(new['id'], 8)
        self.assertEqual(len(store.read(4)['annotations']), 2)
        store.edit_annotation(4, new['id'], SimpleNamespace(comment='수정', revision=1, delete=False))
        with self.assertRaises(HTTPException) as cm:
            store.edit_annotation(4, new['id'], SimpleNamespace(comment='', revision=1, delete=False))
        self.assertEqual(cm.exception.status_code, 409)
        store.edit_annotation(4, new['id'], SimpleNamespace(comment='', revision=2, delete=True))
        self.assertEqual(len(store.read(4)['annotations']), 1)
        with self.assertRaises(HTTPException):
            store.add_annotation(4, SimpleNamespace(kind='highlight', start=2, end=3, exact='문', comment=''))

    def test_existing_http_paths_survive_app_recreation(self):
        with self.target() as pg:
            fork_chat_preview(self.source, pg, self.fixture.schema)
            import_studies(self.source, pg)
        def client():
            app = FastAPI()
            app.include_router(create_router(StudyFixture(self.target)))
            return TestClient(app)
        with client() as first:
            response = first.post('/api/spine/studies/4/annotations', json={
                'kind': 'comment', 'start': 2, 'end': 3, 'exact': '😀', 'comment': '검증'})
            self.assertEqual(response.status_code, 200)
            ident = response.json()['id']
        with client() as restarted:
            response = restarted.get('/api/spine/studies/4')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(any(a['id'] == ident for a in response.json()['annotations']))
            self.assertEqual(restarted.get('/api/spine/studies').status_code, 200)

    def test_different_chat_snapshot_refuses_import(self):
        with self.target() as pg:
            fork_chat_preview(self.source, pg, self.fixture.schema)
            pg.execute("UPDATE conversations SET title='다른 스냅샷' WHERE id=1")
            with self.assertRaisesRegex(ValueError, 'Chat snapshot mismatch'):
                import_studies(self.source, pg)

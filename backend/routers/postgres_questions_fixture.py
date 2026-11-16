"""Read existing question-tracker data from a disposable PG fixture."""
import json
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.rows import dict_row
from pipeline.postgres_graph_fixture import _guard
from routers.spine_questions import AskRequest, FromDocRequest


def create_router(connect, *, run_llm=None, search=None):
    router = APIRouter(prefix='/api/spine/questions')

    @router.get('/creation-runs/{run_id}')
    def creation_run(run_id: UUID):
        with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            _guard(conn)
            cur.execute('SELECT id,question_id,status,steps,created_at,finished_at FROM question_creation_runs WHERE id=%s', (run_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, '질문 생성 작업을 찾을 수 없습니다')
            return row

    @router.post('', status_code=201)
    def create(body: AskRequest, request: Request):
        from pipeline.postgres_question_orchestration_fixture import create_question_native, QuestionRunUnresolved, QuestionModelUncertain
        if not body.text.strip():
            raise HTTPException(400, '질문이 비어 있습니다')
        if run_llm is None or search is None:
            raise HTTPException(503, '질문 생성이 준비되지 않았습니다')
        # Optional lower limits are for a deliberate local fixture test only.
        # Normal requests keep the original scan limit.
        test_limit = request.headers.get('x-explorer-fixture-model-limit')
        if test_limit is not None and (not test_limit.isdigit() or not 1 <= int(test_limit) <= 4):
            raise HTTPException(400, '시험 호출 제한이 올바르지 않습니다')
        calls = 0
        budget_hit = False
        def model(prompt, *, task):
            nonlocal calls, budget_hit
            if test_limit is not None and calls >= int(test_limit):
                budget_hit = True
                raise RuntimeError('fixture model call limit reached')
            calls += 1
            return run_llm(prompt, task=task)
        try:
            result = create_question_native(connect, body.text, run_llm=model, search=search,
                created_by=body.created_by if body.created_by in ('user', 'thesis') else 'user',
                narrative_id=body.narrative_id, source_doc_id=body.source_doc_id,
                numeric_limit=1 if test_limit is not None else 40)
        except QuestionRunUnresolved as exc:
            raise HTTPException(409, {'message': str(exc), 'run_id': exc.run_id}) from exc
        except QuestionModelUncertain as exc:
            raise HTTPException(503, {'message': str(exc), 'run_id': exc.run_id}) from exc
        except ValueError as exc:
            raise HTTPException(503, '질문 분해 결과를 확인하지 못했습니다') from exc
        if budget_hit:
            from psycopg.types.json import Jsonb
            result['status'] = 'partial'
            result['steps']['model_limit'] = {'status': 'partial'}
            with connect() as conn:
                _guard(conn)
                conn.execute("UPDATE question_creation_runs SET status='partial',steps=%s WHERE id=%s",
                             (Jsonb(result['steps']), UUID(result['run_id'])))
        tree = detail(result['question_id'])
        if result['status'] != 'completed':
            tree['processing'] = {'status': result['status'], 'run_id': result['run_id'], 'steps': result['steps']}
        return tree

    @router.get('')
    def index(narrative_id: int | None = None, status: str | None = None):
        with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            _guard(conn)
            cur.execute("SELECT q.*,(SELECT count(*) FROM sub_questions s WHERE s.question_id=q.id) AS sub_count "
                        "FROM questions q WHERE q.status != 'dismissed' "
                        "AND (%s::bigint IS NULL OR q.narrative_id=%s) AND (%s::text IS NULL OR %s='' OR q.status=%s) "
                        "ORDER BY q.updated_at DESC NULLS LAST,q.id ASC", (narrative_id, narrative_id, status, status, status))
            return cur.fetchall()

    @router.get('/proxy/{proxy_id}')
    def proxy_detail(proxy_id: int):
        with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            _guard(conn)
            cur.execute('SELECT p.id,p.label,p.modality,p.yes_direction,p.unit,p.tickers,p.extract_hint, '
                        's.text AS sub_question_text,q.id AS question_id,q.text AS question_text '
                        'FROM proxy_registry p LEFT JOIN sub_questions s ON s.id=p.sub_question_id '
                        'LEFT JOIN questions q ON q.id=s.question_id WHERE p.id=%s', (proxy_id,))
            proxy = cur.fetchone()
            if not proxy:
                raise HTTPException(404, '프록시 없음')
            cur.execute("SELECT o.observed_at,o.value_num,o.value_text,o.direction,o.confidence,o.source_type, "
                        "t.row_data AS transcript FROM proxy_observations o LEFT JOIN legacy_snapshot_rows t "
                        "ON t.table_name='transcripts' AND t.row_data->>'id'=o.transcript_id::text "
                        "WHERE o.proxy_id=%s ORDER BY o.observed_at DESC NULLS LAST,o.id DESC LIMIT 60", (proxy_id,))
            observations = []
            for row in cur.fetchall():
                transcript = row.pop('transcript') or {}
                source_type = row.pop('source_type')
                source = None
                if transcript.get('raw_doc_id'):
                    label = transcript.get('ticker') or ''
                    if transcript.get('fiscal_year') and transcript.get('fiscal_period'):
                        label = f"{label} {transcript['fiscal_year']}{transcript['fiscal_period']}".strip()
                    source = {'doc_id': transcript['raw_doc_id'], 'label': label or '컨콜'}
                elif source_type == 'corpus':
                    source = {'doc_id': None, 'label': '코퍼스 여론'}
                observations.append({**row, 'source': source})
            return {**proxy, 'observations': observations}

    @router.get('/{question_id}')
    def detail(question_id: int):
        with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            _guard(conn)
            cur.execute('SELECT * FROM questions WHERE id=%s', (question_id,))
            question = cur.fetchone()
            if not question:
                raise HTTPException(404, '질문 없음')
            cur.execute('SELECT * FROM sub_questions WHERE question_id=%s ORDER BY id', (question_id,))
            subs = cur.fetchall()
            for sub in subs:
                cur.execute('SELECT * FROM proxy_registry WHERE sub_question_id=%s ORDER BY id', (sub['id'],))
                proxies = cur.fetchall()
                for proxy in proxies:
                    cur.execute('SELECT observed_at,value_num,value_text,direction FROM proxy_observations '
                                'WHERE proxy_id=%s ORDER BY observed_at DESC NULLS LAST,id DESC LIMIT 6', (proxy['id'],))
                    proxy['observations'] = cur.fetchall()
                    cur.execute('SELECT count(*) AS n FROM proxy_observations WHERE proxy_id=%s', (proxy['id'],))
                    proxy['obs_count'] = cur.fetchone()['n']
                sub['proxies'] = proxies
            question['sub_questions'] = subs
            cur.execute('SELECT event,answer,beneficiaries,created_at FROM scenarios WHERE question_id=%s '
                        'ORDER BY created_at DESC NULLS LAST LIMIT 1', (question_id,))
            scenario = cur.fetchone()
            if scenario:
                scenario['beneficiaries'] = json.loads(scenario['beneficiaries'] or '[]')
            question['scenario'] = scenario
            if question.get('source_doc_id'):
                cur.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                            "AND row_data->>'id'=%s LIMIT 1", (str(question['source_doc_id']),))
                row = cur.fetchone()
                doc = row['row_data'] if row else None
                question['source_doc'] = {k: doc.get(k) for k in ('id', 'title', 'source_type')} if doc else None
            cur.execute("UPDATE questions SET last_viewed_at=to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS') "
                        'WHERE id=%s', (question_id,))
            return question

    @router.get('/{question_id}/synthesis')
    def synthesis(question_id: int):
        from pipeline.question_report import _hash
        with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(conn)
            cur.execute('SELECT * FROM questions WHERE id=%s', (question_id,))
            question = cur.fetchone()
            if not question:
                raise HTTPException(404, '질문 없음')
            cur.execute('SELECT id,text,verdict FROM sub_questions WHERE question_id=%s ORDER BY id', (question_id,))
            subs = cur.fetchall()
            if not subs:
                return {'status': 'empty', 'body': None, 'created_at': None, 'stale': False}
            for sub in subs:
                cur.execute('SELECT id,label,modality,unit FROM proxy_registry '
                            'WHERE sub_question_id=%s AND active=1 ORDER BY id', (sub['id'],))
                proxies = cur.fetchall()
                for proxy in proxies:
                    cur.execute('SELECT observed_at,value_num,value_text,direction FROM proxy_observations '
                                'WHERE proxy_id=%s ORDER BY observed_at DESC NULLS LAST,id DESC LIMIT 1', (proxy['id'],))
                    proxy['obs'] = cur.fetchone()
                sub['proxies'] = proxies
            grounding = []
            if question['narrative_id']:
                cur.execute("SELECT count(*) AS n FROM legacy_snapshot_tables WHERE table_name IN ('entity_relations','knowledge')")
                if cur.fetchone()['n'] != 2:
                    raise HTTPException(503, '보고서의 근거 자료가 준비되지 않았습니다')
                cur.execute("SELECT k.row_data->>'id' AS knowledge_id, min(e.row_ordinal) AS ordinal "
                            "FROM legacy_snapshot_rows e JOIN legacy_snapshot_rows k ON k.table_name='knowledge' "
                            "AND k.row_data->>'id'=e.row_data->>'promoted_knowledge_id' "
                            "WHERE e.table_name='entity_relations' AND e.row_data->>'narrative_id'=%s "
                            "GROUP BY k.row_data->>'id' ORDER BY ordinal", (str(question['narrative_id']),))
                grounding = [{'knowledge_id': int(row['knowledge_id'])} for row in cur.fetchall()]
            cur.execute('SELECT body,inputs_hash,created_at FROM question_reports WHERE question_id=%s ORDER BY id DESC LIMIT 1', (question_id,))
            cached = cur.fetchone()
            if not cached:
                return {'status': 'empty', 'body': None, 'created_at': None, 'stale': True}
            digest = _hash({'q': question, 'subs': subs, 'grounding': grounding})
            return {'status': 'ok', 'body': cached['body'], 'created_at': cached['created_at'],
                    'stale': cached['inputs_hash'] != digest}
    @router.post('/from-doc')
    def from_doc(body: FromDocRequest):
        # Legacy Q5 derivation: one model call over a document, nothing stored; in-process network blocked.
        from pipeline.questions import derive_questions_from_doc
        from routers.postgres_legacy_read_fixture import _offline
        offline = _offline.set(True)
        try:
            result = derive_questions_from_doc(body.doc_id)
        finally:
            _offline.reset(offline)
        if 'error' in result:
            raise HTTPException(503, result['error'])
        return result

    @router.post('/{question_id}/rollup')
    def rollup(question_id: int):
        # The legacy re-judgement on the PG ledger: judgement fields only, dropped if inputs changed meanwhile.
        from pipeline.postgres_question_rollup_fixture import rollup_question_native
        if run_llm is None:
            raise HTTPException(503, '판정 요약 모델이 준비되지 않았습니다')
        result = rollup_question_native(connect, question_id, run_llm=run_llm)
        if 'error' in result:
            raise HTTPException(404, result['error'])
        if result.get('status') == 'stale':
            raise HTTPException(409, '판정 중 질문이나 관측이 바뀌었습니다. 다시 시도해 주세요.')
        return {key: result[key] for key in ('lead_verdict', 'confirm_verdict', 'divergence', 'changed', 'edges_confirmed')}

    @router.delete('/{question_id}', status_code=204)
    def dismiss(question_id: int):
        with connect() as conn:
            _guard(conn)
            conn.execute("UPDATE questions SET status='dismissed' WHERE id=%s", (question_id,))
        return Response(status_code=204)

    return router

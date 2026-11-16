"""Read existing question-tracker data from a disposable PG fixture."""
import json
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from pipeline.postgres_graph_fixture import _guard


def create_router(connect):
    router = APIRouter(prefix='/api/spine/questions')

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
    return router

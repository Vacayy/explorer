"""Thesis audits are the requester's own in the public mode.

A thesis is the user's own claim: the operator keeps the legacy history (thesis_audits, through the owner
overrides adapter); a member's audits are stored in member_thesis_audits (explicit initialize) and listed only to
that member; an anonymous visitor has none. The audit computation itself is the legacy one, unchanged.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

from pipeline.postgres_graph_fixture import _guard


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute("CREATE TABLE IF NOT EXISTS member_thesis_audits (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
                     "principal TEXT NOT NULL,thesis_text TEXT NOT NULL,result_json TEXT NOT NULL,"
                     "created_at TEXT NOT NULL DEFAULT to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS'))")
        conn.execute('CREATE INDEX IF NOT EXISTS member_thesis_audits_principal ON member_thesis_audits(principal,id)')


def install(app, factory):
    from pipeline.postgres_legacy_projection import requester_is_operator
    from pipeline.postgres_principals import request_principal
    from routers import spine_thesis
    router = APIRouter()

    def member():
        principal = request_principal.get()
        return None if principal is None else 'principal:' + principal

    def ready(conn):
        return conn.execute("SELECT to_regclass('member_thesis_audits')").fetchone()[0] is not None

    @router.post('/api/spine/thesis/audit')
    def audit(body: spine_thesis.ThesisIn):
        if requester_is_operator():
            return spine_thesis.audit(body)
        owner = member()
        if owner is None:
            raise HTTPException(401, 'Authentication required')
        text = (body.text or '').strip()
        if len(text) < 10:
            raise HTTPException(400, '논지가 너무 짧습니다')
        with factory() as conn:
            _guard(conn)
            if not ready(conn):  # refused before any model call
                raise HTTPException(503, '회원 논지 감사가 준비되지 않았습니다')
        from pipeline.thesis import audit_thesis
        result = audit_thesis(text)
        with factory() as conn:
            row = conn.execute('INSERT INTO member_thesis_audits(principal,thesis_text,result_json) VALUES (%s,%s,%s) '
                               'RETURNING id,created_at', (owner, text, json.dumps(result, ensure_ascii=False))).fetchone()
        return {'id': row[0], 'created_at': row[1], 'thesis_text': text, **result}

    @router.get('/api/spine/thesis/audits')
    def audits():
        if requester_is_operator():
            return spine_thesis.audits()
        owner = member()
        with factory() as conn:
            if owner is None or not ready(conn):
                return []
            rows = conn.execute('SELECT id,thesis_text,result_json,created_at FROM member_thesis_audits WHERE principal=%s '
                                'ORDER BY id DESC LIMIT 30', (owner,)).fetchall()
        return [{'id': r[0], 'created_at': r[3], 'preview': (r[1] or '')[:80],
                 'n_claims': len(json.loads(r[2]).get('claims', []))} for r in rows]

    @router.get('/api/spine/thesis/{audit_id}')
    def one(audit_id: int):
        if requester_is_operator():
            return spine_thesis.one(audit_id)
        owner = member()
        with factory() as conn:
            row = conn.execute('SELECT id,thesis_text,result_json,created_at FROM member_thesis_audits WHERE id=%s AND principal=%s',
                               (audit_id, owner)).fetchone() if owner is not None and ready(conn) else None
        if row is None:
            raise HTTPException(404, '감사 결과 없음')
        return {'id': row[0], 'created_at': row[3], 'thesis_text': row[1], **json.loads(row[2])}

    # Ahead of the legacy thesis routes (the same paths), so every request comes here first.
    app.router.routes[:0] = [route for route in router.routes if isinstance(route, APIRoute)]

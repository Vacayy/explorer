"""Whose studies a request reads on the single-path candidate.

A member's standalone studies (study_principals) and projects (study_project_principals; a project's documents
follow the project) are that member's only; rows without a mapping are the operator's, as before. The tables are
created by an explicit deployment step; until then members get no studies (503 on writes).
"""
from fastapi import HTTPException

from pipeline.postgres_graph_fixture import _guard


def owner():
    """'principal:<id>' for a signed-in member, None for the operator (and every request in the private mode);
    an anonymous public request has no studies (401)."""
    from pipeline.postgres_principals import conversation_owner, request_principal
    from security.access_boundary import configured_access_mode
    if configured_access_mode() == 'public' and request_principal.get() is None:
        raise HTTPException(401, 'Authentication required')
    return conversation_owner(None)


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS study_project_principals (project_id BIGINT PRIMARY KEY '
                     'REFERENCES study_projects(id) ON DELETE CASCADE,principal TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS study_principals (study_id BIGINT PRIMARY KEY '
                     'REFERENCES study_sessions(id) ON DELETE CASCADE,principal TEXT NOT NULL)')
        # One standalone study per document *per requester* now (serialized by open_document's lock per document
        # and owner); a project's documents stay unique within the project.
        conn.execute('DROP INDEX IF EXISTS study_session_document_project')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS study_session_document_in_project ON study_sessions(document_id,project_id) '
                     'WHERE project_id<>0')


def mapped(conn):
    return conn.execute("SELECT to_regclass('study_principals')").fetchone()[0] is not None


def _require(conn, member):
    if member is not None and not mapped(conn):
        raise HTTPException(503, '회원 스터디가 준비되지 않았습니다')


def project_visible(conn, alias='p'):
    """(SQL condition, params) for projects the requester may see."""
    member = owner()
    if not mapped(conn):
        _require(conn, member)
        return 'true', ()
    if member is None:
        return f'NOT EXISTS (SELECT 1 FROM study_project_principals o WHERE o.project_id={alias}.id)', ()
    return f'EXISTS (SELECT 1 FROM study_project_principals o WHERE o.project_id={alias}.id AND o.principal=%s)', (member,)


def session_visible(conn, alias='s'):
    """(SQL condition, params) for study sessions the requester may see: standalone ones by their own mapping,
    a project's documents by the project's."""
    member = owner()
    if not mapped(conn):
        _require(conn, member)
        return 'true', ()
    if member is None:
        return (f'(CASE WHEN {alias}.project_id=0 THEN NOT EXISTS (SELECT 1 FROM study_principals o WHERE o.study_id={alias}.id) '
                f'ELSE NOT EXISTS (SELECT 1 FROM study_project_principals o WHERE o.project_id={alias}.project_id) END)'), ()
    return (f'(CASE WHEN {alias}.project_id=0 THEN EXISTS (SELECT 1 FROM study_principals o WHERE o.study_id={alias}.id AND o.principal=%s) '
            f'ELSE EXISTS (SELECT 1 FROM study_project_principals o WHERE o.project_id={alias}.project_id AND o.principal=%s) END)'), (member, member)


def claim_session(conn, study_id):
    member = owner()
    if member is not None:
        conn.execute('INSERT INTO study_principals VALUES (%s,%s)', (study_id, member))


def claim_project(conn, project_id):
    member = owner()
    if member is not None:
        conn.execute('INSERT INTO study_project_principals VALUES (%s,%s)', (project_id, member))


def check_session(conn, study_id):
    predicate, params = session_visible(conn)
    if conn.execute(f'SELECT 1 FROM study_sessions s WHERE s.id=%s AND {predicate}', (study_id, *params)).fetchone() is None:
        raise HTTPException(404, '스터디를 찾을 수 없습니다')


def check_project(conn, project_id):
    predicate, params = project_visible(conn)
    if conn.execute(f'SELECT 1 FROM study_projects p WHERE p.id=%s AND {predicate}', (project_id, *params)).fetchone() is None:
        raise HTTPException(404, '스터디 프로젝트를 찾을 수 없습니다.')

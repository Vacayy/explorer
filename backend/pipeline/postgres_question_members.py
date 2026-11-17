"""Member-owned questions (question_principals) stay inside their question.

The daily refresh judges only the operator's questions, and a member's judgment writes nothing
to the shared graph (observation projection, edge confirmation); its verdict stays on the question.
"""


def _mapped(pg):
    return pg.execute("SELECT to_regclass('question_principals')").fetchone()[0] is not None


def member_question(pg, question_id):
    return _mapped(pg) and pg.execute('SELECT 1 FROM question_principals WHERE question_id=%s', (question_id,)).fetchone() is not None


def operator_only(pg, column):
    """SQL condition keeping rows whose question (`column`, NULL for seed proxies) is not a member's."""
    if not _mapped(pg):
        return 'true'
    return f'NOT EXISTS (SELECT 1 FROM question_principals m WHERE m.question_id={column})'

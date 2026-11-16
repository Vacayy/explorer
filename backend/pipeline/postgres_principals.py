"""Whose personal ledger a request reads on the single-path candidate.

The access boundary sets `request_principal` for a signed-in request (principals.id, as identity sessions
resolve it). The operator's records are the legacy owner's: the one account the legacy mapping names (its
data is also what the projection shows to legacy reads). Any other principal gets its own account, created
on first use. Without a principal the operator's account answers only in the private (loopback) mode; in
the public mode such a request is refused (PrincipalRequired, answered 401).
"""
from contextvars import ContextVar

from pipeline.postgres_graph_fixture import _guard

request_principal = ContextVar('request_principal', default=None)


class PrincipalRequired(PermissionError):
    """A personal ledger was asked for without a principal outside the loopback (private) mode."""


def _effective_principal(operator):
    """The one place deciding whose ledger an unauthenticated request reads: the operator's only in the private
    (loopback) mode; in the public mode an anonymous request never reads anyone's records."""
    from security.access_boundary import configured_access_mode
    principal = request_principal.get()
    if principal is not None:
        return principal
    if configured_access_mode() != 'private':
        raise PrincipalRequired('Authentication required')
    return operator


def operator_principal(conn):
    rows = conn.execute('SELECT a.principal FROM fixture_portfolio_legacy_mapping m '
                        'JOIN fixture_portfolio_accounts a ON a.id=m.account_id').fetchall()
    if len(rows) != 1:
        raise LookupError('Owner portfolio ledger unavailable')
    return rows[0][0]


def owner_account(conn, *, create=False):
    """(account id, principal) of the request's personal ledger; the id is None for a member with no records yet
    (reads answer empty) unless `create` (a write)."""
    operator = operator_principal(conn)
    principal = _effective_principal(operator)
    if principal != operator and create:
        conn.execute('INSERT INTO fixture_portfolio_accounts(principal) VALUES (%s) ON CONFLICT DO NOTHING', (principal,))
    row = conn.execute('SELECT id FROM fixture_portfolio_accounts WHERE principal=%s', (principal,)).fetchone()
    return (row[0] if row else None), principal


def remap_operator(conn, principal):
    """Attribute the operator's (legacy owner's) records to a real principal: data rows only, in one transaction."""
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT 1 FROM principals WHERE id=%s AND role='operator' AND enabled", (principal,)).fetchone() is None:
            raise ValueError('An enabled operator principal is required')
        if conn.execute('SELECT 1 FROM fixture_portfolio_accounts WHERE principal=%s', (principal,)).fetchone():
            raise ValueError('That principal already has its own account')
        old = operator_principal(conn)
        conn.execute('UPDATE fixture_portfolio_accounts SET principal=%s WHERE principal=%s', (principal, old))
        return old

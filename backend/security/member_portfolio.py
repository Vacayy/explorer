"""Explicitly provisioned ownership for the existing portfolio ledger.

No request-time schema migration, owner inference, provider calls or legacy writes.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from pipeline import portfolio as pf


class TransactionUnavailable(Exception):
    pass


def initialize_ownership(conn):
    """Deployment-only migration, after consistent backup and owner review.

    Existing NULL-owned rows stay intact. This does not assign an operator or
    migrate legacy jobs, principles, alerts or thesis ownership.
    """
    if conn.in_transaction:
        raise ValueError('Ownership preparation requires a fresh transaction')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(stock_groups)')}
        if not {'id', 'kind', 'name'}.issubset(columns):
            raise ValueError('Portfolio schema is not initialized')
        if 'owner_id' not in columns:
            conn.execute('ALTER TABLE stock_groups ADD COLUMN owner_id TEXT')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_owner ON stock_groups(owner_id) "
                     "WHERE kind='portfolio' AND owner_id IS NOT NULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS member_portfolio_principles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES stock_groups(id),
            text TEXT NOT NULL, rules_json TEXT NOT NULL, notes_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_member_principles_group ON member_portfolio_principles(group_id,id)')


class MemberPortfolio:
    def __init__(self, source: Path, owner: str):
        if not isinstance(owner, str) or not owner:
            raise ValueError('Explicit member required')
        self.source, self.owner = Path(source).absolute(), owner

    @contextmanager
    def connection(self, *, write=False):
        conn = sqlite3.connect(self.source.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            if not write:
                conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            # Deliberately fail closed until explicit deployment preparation.
            conn.execute('SELECT owner_id FROM stock_groups LIMIT 0')
            indexes = {row['name']: row for row in conn.execute('PRAGMA index_list(stock_groups)')}
            if 'idx_portfolio_owner' not in indexes or not indexes['idx_portfolio_owner']['unique']:
                raise ValueError('Portfolio ownership is not initialized')
            yield conn
            if write:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def group(self, conn, *, create=False):
        row = conn.execute("SELECT id FROM stock_groups WHERE kind='portfolio' AND owner_id=?", (self.owner,)).fetchone()
        if row:
            return row['id']
        if create:
            return conn.execute("INSERT INTO stock_groups(name,kind,owner_id) VALUES (?,'portfolio',?)",
                                (pf.GROUP_NAME, self.owner)).lastrowid
        # Positive autoincrement IDs; no legacy fallback and no GET-side writes.
        return 0

    def read(self, operation):
        with self.connection() as conn:
            return operation(conn, gid=self.group(conn))

    def add(self, body):
        with self.connection(write=True) as conn:
            gid = self.group(conn, create=True)
            return pf.add_transaction(conn, body.model_dump(exclude={'fund_shortfall'}),
                                      fund_shortfall=body.fund_shortfall, gid=gid, commit=False)

    def delete(self, tx_id):
        with self.connection(write=True) as conn:
            gid = self.group(conn)
            if not gid or not conn.execute('SELECT 1 FROM portfolio_transactions WHERE id=? AND group_id=?', (tx_id,gid)).fetchone():
                raise TransactionUnavailable()
            pf.delete_transaction(conn, tx_id, gid=gid, commit=False)

    def companies(self, query):
        # Only shared company code/name, never ownership, holdings or search/RAG.
        if not query:
            return []
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('''SELECT stock_code,corp_name FROM companies
                WHERE length(stock_code)=6 AND stock_code NOT GLOB '*[^0-9A-Z]*'
                AND corp_name IS NOT NULL AND (instr(stock_code,?)>0 OR instr(corp_name,?)>0)
                ORDER BY stock_code LIMIT 20''', (query,query))]

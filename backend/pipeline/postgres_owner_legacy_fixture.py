"""Owner ledger for legacy multi-table writes (groups) in the single-path preview.

Rows keep their legacy column names as JSONB, keyed by the legacy integer PK, so
the unchanged legacy write code can run against TEMP copies and only its diff is
stored here. Highest IDs ever issued are kept so deleted IDs are never reused.
Rows of the explicitly mapped portfolio group stay with the portfolio ledger.
"""
import json
import sqlite3
from pathlib import Path

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

TABLES = ('stock_groups', 'stock_group_members', 'watch_rules', 'watch_evaluations',
          # User-edited reference records (industry universe, business segments, IR notes), added by `adopt`.
          'industry_groups', 'industry_members', 'business_segments', 'ir_notes')


# Tables a member's own groups use; a member's diff may touch only these (pipeline.postgres_principals).
MEMBER_TABLES = ('stock_groups', 'stock_group_members', 'watch_rules', 'watch_evaluations')


def initialize_member_rows(conn):
    """Explicit deployment step: rows may belong to a member's account (NULL: the mapped owner's, as before)."""
    _guard(conn)
    with conn.transaction():
        conn.execute('ALTER TABLE owner_legacy_rows ADD COLUMN IF NOT EXISTS account_id BIGINT REFERENCES fixture_portfolio_accounts(id)')
        conn.execute('CREATE INDEX IF NOT EXISTS owner_legacy_rows_account ON owner_legacy_rows(account_id) WHERE account_id IS NOT NULL')


def _accounts(conn):
    return conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() "
                        "AND table_name='owner_legacy_rows' AND column_name='account_id'").fetchone() is not None


def member_rows(conn, account):
    """A member's own group rows, by table."""
    rows = {table: [] for table in MEMBER_TABLES}
    if _accounts(conn):
        for table, data in conn.execute('SELECT table_name,row_data FROM owner_legacy_rows WHERE account_id=%s '
                                        'ORDER BY table_name,pk', (account,)):
            rows[table].append(data)
    return rows


def portfolio_group(conn):
    rows = conn.execute('SELECT legacy_group_id FROM fixture_portfolio_legacy_mapping').fetchall()
    if len(rows) != 1:
        raise LookupError('Exactly one explicitly mapped owner is required')
    return rows[0][0]


def initialize(conn, backup_dir):
    """Copy the group tables and their AUTOINCREMENT high-water marks from the base generation."""
    _guard(conn)
    backup = Path(backup_dir)
    manifest = json.loads((backup / 'manifest.json').read_text())
    path = backup / manifest['file']
    if path.stat().st_size != manifest['size_bytes']:
        raise ValueError('Backup file does not match its manifest')
    source = sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)
    try:
        sequences = dict(source.execute('SELECT name,seq FROM sqlite_sequence WHERE name IN (%s)' % ','.join('?' * len(TABLES)), TABLES))
        with conn.transaction():
            if conn.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is not None:
                raise ValueError('Owner legacy ledger already initialized')
            group = portfolio_group(conn)
            conn.execute('CREATE TABLE owner_legacy_rows (table_name TEXT NOT NULL,pk BIGINT NOT NULL,row_data JSONB NOT NULL,'
                         'PRIMARY KEY(table_name,pk))')
            conn.execute('CREATE TABLE owner_legacy_sequences (table_name TEXT PRIMARY KEY,seq BIGINT NOT NULL)')
            conn.execute('CREATE TABLE owner_legacy_version (singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK(singleton),'
                         'counter BIGINT NOT NULL)')
            conn.execute('INSERT INTO owner_legacy_version VALUES (true,0)')
            counts = {}
            for table in TABLES:
                rows = [row for (row,) in conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s', (table,))]
                if table == 'stock_group_members':
                    rows = [row for row in rows if row.get('group_id') != group]
                if len(rows) != source.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] - (
                        source.execute('SELECT count(*) FROM stock_group_members WHERE group_id=?', (group,)).fetchone()[0]
                        if table == 'stock_group_members' else 0):
                    raise ValueError(f'Snapshot and backup differ: {table}')
                with conn.cursor().copy('COPY owner_legacy_rows (table_name,pk,row_data) FROM STDIN') as copy:
                    for row in rows:
                        copy.write_row((table, row['id'], json.dumps(row, ensure_ascii=False)))
                high = max([sequences.get(table, 0), *(row['id'] for row in rows)] or [0])
                conn.execute('INSERT INTO owner_legacy_sequences VALUES (%s,%s)', (table, high))
                counts[table] = len(rows)
            return counts
    finally:
        source.close()


def load(conn):
    """Return (version, the mapped owner's rows by table, sequences) from one consistent read."""
    version = conn.execute('SELECT counter FROM owner_legacy_version WHERE singleton').fetchone()[0]
    rows = {table: [] for table in TABLES}
    owner = ' WHERE account_id IS NULL' if _accounts(conn) else ''  # members' rows stay out of the owner's view
    for table, data in conn.execute(f'SELECT table_name,row_data FROM owner_legacy_rows{owner} ORDER BY table_name,pk'):
        rows[table].append(data)
    return version, rows, dict(conn.execute('SELECT table_name,seq FROM owner_legacy_sequences').fetchall())


def apply(conn, started, changes, sequences, account=None):
    """Store one successful request's diff, refusing if another write landed meanwhile. `account`: a member's
    diff, kept on that member's rows (only MEMBER_TABLES); None: the mapped owner's."""
    if conn.execute('SELECT counter FROM owner_legacy_version WHERE singleton FOR UPDATE').fetchone()[0] != started:
        raise RuntimeError('Owner records changed during the request')
    accounts = _accounts(conn)
    if account is not None and not accounts:
        raise PermissionError('Member groups are not initialized')
    group = portfolio_group(conn)
    for table, upserts, deletes in changes:
        if account is not None and table not in MEMBER_TABLES and (upserts or deletes):
            raise PermissionError('A member changes only their own groups')
        if table == 'stock_groups' and group in deletes:
            raise PermissionError('The mapped portfolio group is kept by the portfolio ledger')
        if table == 'stock_group_members' and any(row.get('group_id') == group for row in upserts.values()):
            raise PermissionError('Portfolio members are kept by the portfolio ledger')
        owner = ' AND account_id IS NOT DISTINCT FROM %s' if accounts else ''
        for pk in deletes:
            if conn.execute('DELETE FROM owner_legacy_rows WHERE table_name=%s AND pk=%s' + owner,
                            (table, pk, *((account,) if accounts else ()))).rowcount != 1:
                raise PermissionError('Not the requester\'s row')
        for pk, row in upserts.items():
            if accounts:
                stored = conn.execute('INSERT INTO owner_legacy_rows (table_name,pk,row_data,account_id) VALUES (%s,%s,%s,%s) '
                                      'ON CONFLICT (table_name,pk) DO UPDATE SET row_data=excluded.row_data '
                                      'WHERE owner_legacy_rows.account_id IS NOT DISTINCT FROM excluded.account_id',
                                      (table, pk, Jsonb(row), account)).rowcount
                if stored != 1:
                    raise PermissionError('Not the requester\'s row')
            else:
                conn.execute('INSERT INTO owner_legacy_rows VALUES (%s,%s,%s) ON CONFLICT (table_name,pk) '
                             'DO UPDATE SET row_data=excluded.row_data', (table, pk, Jsonb(row)))
    for table, seq in sequences.items():
        conn.execute('UPDATE owner_legacy_sequences SET seq=GREATEST(seq,%s) WHERE table_name=%s', (seq, table))
    conn.execute('UPDATE owner_legacy_version SET counter=counter+1')


def adopt(conn, tables):
    """Move more user-edited tables into the ledger, rows unchanged, IDs never reissued."""
    _guard(conn)
    with conn.transaction():
        counts = {}
        for table in tables:
            if table not in TABLES:
                raise ValueError(f'Not an owner legacy table: {table}')
            if conn.execute('SELECT 1 FROM owner_legacy_sequences WHERE table_name=%s', (table,)).fetchone():
                raise ValueError(f'Already in the ledger: {table}')
            rows = [row for (row,) in conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s', (table,))]
            expected = conn.execute('SELECT row_count FROM legacy_snapshot_tables WHERE table_name=%s', (table,)).fetchone()[0]
            if len(rows) != expected:
                raise ValueError(f'Visible rows differ from the table count: {table}')
            with conn.cursor().copy('COPY owner_legacy_rows (table_name,pk,row_data) FROM STDIN') as copy:
                for row in rows:
                    copy.write_row((table, row['id'], json.dumps(row, ensure_ascii=False)))
            sequence = conn.execute("SELECT max((row_data->>'seq')::bigint) FROM legacy_snapshot_rows "
                                    "WHERE table_name='sqlite_sequence' AND row_data->>'name'=%s", (table,)).fetchone()[0]
            conn.execute('INSERT INTO owner_legacy_sequences VALUES (%s,%s)',
                         (table, max([sequence or 0, *(row['id'] for row in rows)])))
            counts[table] = len(rows)
        conn.execute('UPDATE owner_legacy_version SET counter=counter+1')
        return counts

"""Members of the public service into the candidate's principal ledgers (cutover step 4, pilot plan; runbook R3).

Sources are copies taken during the freeze (never the live files): the public service's identity SQLite (users,
google_identities) and its main SQLite (stock_groups.owner_id portfolios, portfolio_transactions,
member_portfolio_principles, member_saved_documents). Users keep their ids (principals, google_identities); sessions
are not carried (everyone signs in again). Each member's records get new ids in that member's own account, with a
mapping from the original ids (member_import_ids). Nothing is printed of the contents: only counts and, per principal, a hash of the
records computed from the source and again from the candidate after the import (equal = carried over unchanged).
The operator's records come from the MacBook copy instead (the operator user is imported for its identity only).
"""
import hashlib
import json
import sqlite3

from pipeline.postgres_graph_fixture import _guard


def _digest(rows):
    return hashlib.sha256(json.dumps(sorted(rows), ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _source(identity, main, user_id):
    """One member's records in the public service copy, in the candidate's terms (no ids)."""
    groups = [row[0] for row in main.execute("SELECT id FROM stock_groups WHERE kind='portfolio' AND owner_id=?", (user_id,))]
    marks = ','.join('?' * len(groups))
    transactions = [tuple(row) for row in main.execute(
        f'SELECT trade_date,kind,stock_code,amount,price,note FROM portfolio_transactions WHERE group_id IN ({marks}) '
        'ORDER BY trade_date,id', groups)] if groups else []
    principles = [tuple(row) for row in main.execute(
        f'SELECT text,rules_json,notes_json FROM member_portfolio_principles WHERE group_id IN ({marks}) ORDER BY id',
        groups)] if groups else []
    saved = [tuple(row) for row in main.execute(
        'SELECT doc_id,note FROM member_saved_documents WHERE owner_user_id=? ORDER BY id', (user_id,))]
    return {'transactions': transactions, 'principles': principles, 'saved': saved, 'groups': groups}


def _target(pg, account):
    rows = lambda sql: [tuple(row) for row in pg.execute(sql, (account,))]  # noqa: E731
    return {'transactions': rows('SELECT trade_date,kind,stock_code,amount,price,note FROM fixture_portfolio_transactions '
                                 'WHERE account_id=%s ORDER BY trade_date,id'),
            'principles': rows('SELECT text,rules_json,notes_json FROM fixture_portfolio_principles WHERE account_id=%s ORDER BY id'),
            'saved': [(int(ref), note) for ref, note in rows("SELECT ref,note FROM owner_saved_items WHERE account_id=%s "
                                                              "AND kind='doc' ORDER BY id")]}


def _hashes(records):
    return {name: _digest(records[name]) for name in ('transactions', 'principles', 'saved')}


def import_members(pg, identity_path, main_path):
    """Import every user and the members' records in one transaction; returns the report (counts, hashes, id maps)."""
    _guard(pg)
    identity = sqlite3.connect(f'file:{identity_path}?mode=ro', uri=True)
    main = sqlite3.connect(f'file:{main_path}?mode=ro', uri=True)
    report = {'principals': 0, 'identities': 0, 'members': {}, 'operators': []}
    try:
        users = identity.execute('SELECT id,role,enabled FROM users ORDER BY id').fetchall()
        with pg.transaction():
            pg.execute('CREATE TABLE IF NOT EXISTS member_import_ids (principal TEXT NOT NULL,source_table TEXT NOT NULL,'
                       'source_id BIGINT NOT NULL,target_id BIGINT NOT NULL,imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),'
                       'PRIMARY KEY (source_table,source_id))')
            for user_id, role, enabled in users:
                if pg.execute('SELECT 1 FROM principals WHERE id=%s', (user_id,)).fetchone():
                    raise ValueError(f'Principal already present: {user_id[:8]}… (the import runs once, on a fresh ledger)')
                pg.execute('INSERT INTO principals(id,role,enabled) VALUES (%s,%s,%s)', (user_id, role, bool(enabled)))
                report['principals'] += 1
            for issuer, subject, user_id in identity.execute('SELECT issuer,subject,user_id FROM google_identities'):
                pg.execute('INSERT INTO google_identities(issuer,subject,principal_id) VALUES (%s,%s,%s)', (issuer, subject, user_id))
                report['identities'] += 1
            for user_id, role, _enabled in users:
                if role == 'operator':
                    report['operators'].append(user_id[:8])
                    continue
                records = _source(identity, main, user_id)
                if not (records['transactions'] or records['principles'] or records['saved']):
                    continue
                account = pg.execute('INSERT INTO fixture_portfolio_accounts(principal) VALUES (%s) RETURNING id',
                                     (user_id,)).fetchone()[0]
                mapping = {'transactions': {}, 'principles': {}, 'saved': {}}
                marks = ','.join('?' * len(records['groups']))
                if records['groups']:
                    for old, *values in main.execute(
                            'SELECT id,trade_date,kind,stock_code,amount,price,note FROM portfolio_transactions '
                            f'WHERE group_id IN ({marks}) ORDER BY trade_date,id', records['groups']):
                        mapping['transactions'][old] = pg.execute(
                            'INSERT INTO fixture_portfolio_transactions(account_id,trade_date,kind,stock_code,amount,price,note) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id', (account, *values)).fetchone()[0]
                    for old, *values in main.execute(
                            'SELECT id,text,rules_json,notes_json,created_at FROM member_portfolio_principles '
                            f'WHERE group_id IN ({marks}) ORDER BY id', records['groups']):
                        mapping['principles'][old] = pg.execute(
                            'INSERT INTO fixture_portfolio_principles(account_id,text,rules_json,notes_json,created_at) '
                            'VALUES (%s,%s,%s,%s,%s) RETURNING id', (account, *values)).fetchone()[0]
                for old, doc_id, note, created in main.execute(
                        'SELECT id,doc_id,note,created_at FROM member_saved_documents WHERE owner_user_id=? ORDER BY id', (user_id,)):
                    document = pg.execute("SELECT row_data->>'title', row_data->>'url' FROM legacy_snapshot_rows "
                                          "WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
                    mapping['saved'][old] = pg.execute(
                        "INSERT INTO owner_saved_items(account_id,kind,ref,url,title,note,created_at) VALUES "
                        "(%s,'doc',%s,%s,%s,%s,%s) RETURNING id",
                        (account, str(doc_id), document and document[1], document and document[0], note, created)).fetchone()[0]
                for name, table in (('transactions', 'portfolio_transactions'), ('principles', 'member_portfolio_principles'),
                                    ('saved', 'member_saved_documents')):
                    for old, new in mapping[name].items():
                        pg.execute('INSERT INTO member_import_ids(principal,source_table,source_id,target_id) VALUES (%s,%s,%s,%s)',
                                   (user_id, table, old, new))
                carried = _target(pg, account)
                source, target = _hashes(records), _hashes(carried)
                report['members'][user_id[:8]] = {
                    'counts': {name: len(records[name]) for name in ('transactions', 'principles', 'saved')},
                    'source': source, 'candidate': target, 'equal': source == target,
                    'id_map': {name: len(values) for name, values in mapping.items()}}
                if source != target:
                    raise RuntimeError(f'Member {user_id[:8]}… records differ after the import; nothing kept')
        return report
    finally:
        identity.close()
        main.close()

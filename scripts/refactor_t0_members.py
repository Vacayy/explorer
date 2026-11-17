"""Cutover step 4 (scripts/refactor_t0.sh members): the public service's users into the live candidate, once, then the
operator's ledgers to its real principal. The public service has no member records (the caller checks the counts), so
the member tables given to the import are empty; the identity copy is /copy/identity.sqlite."""
import os
import sqlite3

import psycopg

from pipeline import postgres_principals
from pipeline.postgres_member_import import import_members

members = sqlite3.connect('/tmp/members.sqlite')
members.executescript(
    'CREATE TABLE stock_groups (id INTEGER PRIMARY KEY, kind TEXT, name TEXT, owner_id TEXT);'
    'CREATE TABLE portfolio_transactions (id INTEGER PRIMARY KEY, group_id INTEGER, trade_date TEXT, kind TEXT, '
    'stock_code TEXT, amount REAL, price REAL, note TEXT, created_at TEXT);'
    'CREATE TABLE member_portfolio_principles (id INTEGER PRIMARY KEY, group_id INTEGER, text TEXT, rules_json TEXT, '
    'notes_json TEXT, created_at TEXT);'
    'CREATE TABLE member_saved_documents (id INTEGER PRIMARY KEY, owner_user_id TEXT, doc_id INTEGER, '
    'saved_fingerprint TEXT, note TEXT, created_at TEXT);')
members.close()
dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
with psycopg.connect(dsn, options=f'-c search_path={schema}') as pg:
    report = import_members(pg, '/copy/identity.sqlite', '/tmp/members.sqlite')
    print('principals', report['principals'], 'identities', report['identities'], 'operators', len(report['operators']),
          'members with records', len(report['members']))
    operators = [row[0] for row in pg.execute("SELECT id FROM principals WHERE role='operator' AND enabled")]
    if len(operators) != 1:
        raise SystemExit(f'{len(operators)} operator principals: map the owner by hand')
    postgres_principals.remap_operator(pg, operators[0])
    print('operator ledgers mapped')

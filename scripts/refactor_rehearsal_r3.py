"""Sync rehearsal R3: the operator's personal records, candidate ledger against the new source (runbook R3).

Three-way per record against the 11-14 base (/base/stock_explorer.db, the state both sides started from): equal on
both sides; changed only on the MacBook (take the source); changed only in the candidate (keep the candidate); changed
on both sides differently (conflict, listed, never merged automatically). Records are matched by their natural key;
content compares the columns both sides keep. Prints counts and the conflicting keys only (no content), and writes the
same to /rehearsal/r3-report.json when that directory is writable.

  python /app/scripts/refactor_rehearsal_r3.py
"""
import hashlib
import json
import os
import sqlite3
import sys

import psycopg

SOURCE, BASE = '/rehearsal/source.db', '/base/stock_explorer.db'
# (candidate ledger, legacy table, natural key columns, content columns)
LEDGERS = (('owner_follows', 'follows', ('entity_id',), ()),
           ('owner_saved_items', 'saved_items', ('kind', 'ref'), ('url', 'title', 'subtitle', 'note')),
           ('owner_channel_reads', 'channel_reads', ('channel',), ('read_until',)),
           ('owner_kalshi_pins', 'kalshi_pins', ('event_ticker',), ('series_ticker',)),
           ('owner_tracker_conditions', 'tracker_conditions', ('id',),
            ('stock_code', 'role', 'kind', 'level', 'ma', 'label', 'note', 'done')),
           ('owner_trade_follow', 'trade_follow', ('hs_code',), ('item_name', 'group_label', 'active')),
           ('owner_transcript_pins', 'transcript_follow', ('ticker',), ('core_pinned',)),
           ('fixture_portfolio_principles', 'portfolio_principles', ('text',), ('rules_json', 'notes_json')))
# Ledgers holding only the operator's choices over a collected catalogue: an item without a ledger row is unchanged.
CHOICES = {'owner_trade_follow'}
# Portfolio transactions have no natural key: compared as multisets of their content.
TRANSACTIONS = ('trade_date', 'kind', 'stock_code', 'amount', 'price', 'note')


def _digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _norm(value):
    return None if value in (None, '') else (int(value) if isinstance(value, bool) else value)


def _legacy(db, table, key, content):
    if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone() is None:
        return {}
    have = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
    columns = [c for c in content if c in have]
    rows = db.execute(f'SELECT {",".join(key + tuple(columns))} FROM "{table}"').fetchall()
    return {tuple(map(str, row[:len(key)])): _digest([_norm(v) for v in row[len(key):]]) for row in rows}, columns


def three_way(base, candidate, source):
    out = {'same': 0, 'take_source': 0, 'keep_candidate': 0, 'conflict': 0, 'conflicts': []}
    for key in sorted(set(base) | set(candidate) | set(source)):
        b, c, s = base.get(key), candidate.get(key), source.get(key)
        if c == s:
            out['same'] += 1
        elif c == b:
            out['take_source'] += 1
        elif s == b:
            out['keep_candidate'] += 1
        else:
            out['conflict'] += 1
            out['conflicts'].append({'key': list(key), 'base': b is not None, 'candidate': c is not None, 'source': s is not None})
    return out


def main():
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    if schema == os.environ.get('TRIAL_LIVE_SCHEMA'):
        raise SystemExit('The rehearsal schema, never the live one')
    base = sqlite3.connect(f'file:{BASE}?mode=ro&immutable=1', uri=True)
    source = sqlite3.connect(f'file:{SOURCE}?mode=ro', uri=True)
    report = {}
    with psycopg.connect(dsn, options=f'-c search_path={schema}') as pg:
        for ledger, table, key, content in LEDGERS:
            b, columns = _legacy(base, table, key, content)
            s, _ = _legacy(source, table, key, content)
            rows = pg.execute(f'SELECT {",".join(key + tuple(columns))} FROM "{ledger}"').fetchall()
            c = {tuple(map(str, row[:len(key)])): _digest([_norm(v) for v in row[len(key):]]) for row in rows}
            if ledger in CHOICES:
                c = {**b, **c}
            report[ledger] = three_way(b, c, s)
        multiset = lambda rows: {(_digest([_norm(v) for v in row]), n): 1 for row in set(rows)  # noqa: E731
                                 for n in range(rows.count(row))}
        legacy_rows = lambda db: [tuple(row) for row in db.execute(  # noqa: E731
            f'SELECT {",".join(TRANSACTIONS)} FROM portfolio_transactions')]
        candidate = [tuple(row) for row in pg.execute(f'SELECT {",".join(TRANSACTIONS)} FROM fixture_portfolio_transactions')]
        report['fixture_portfolio_transactions'] = three_way(
            {k: 'x' for k in multiset(legacy_rows(base))}, {k: 'x' for k in multiset(candidate)},
            {k: 'x' for k in multiset(legacy_rows(source))})
        # Group rows and other legacy multi-table records, kept by their legacy id.
        from pipeline.postgres_owner_legacy_fixture import TABLES
        for table in TABLES:
            have = {row[1] for row in source.execute(f'PRAGMA table_info("{table}")')}
            if not have:
                continue
            ledger_rows = {str(pk): data for pk, data in pg.execute(
                'SELECT pk, row_data FROM owner_legacy_rows WHERE table_name=%s AND account_id IS NULL', (table,))}
            columns = sorted(have & set().union(*(d.keys() for d in ledger_rows.values()))) if ledger_rows else sorted(have)
            pick = lambda db: {str(row[0]): _digest([_norm(v) for v in row[1:]]) for row in db.execute(  # noqa: E731
                f'SELECT id,{",".join(c for c in columns if c != "id")} FROM "{table}"')}
            c = {pk: _digest([_norm(d.get(col)) for col in columns if col != 'id']) for pk, d in ledger_rows.items()}
            report[f'owner_legacy_rows[{table}]'] = three_way(
                {(k,): v for k, v in pick(base).items()}, {(k,): v for k, v in c.items()},
                {(k,): v for k, v in pick(source).items()})
    totals = {name: sum(r[name] for r in report.values()) for name in ('same', 'take_source', 'keep_candidate', 'conflict')}
    result = {'totals': totals, 'ledgers': {k: {n: v for n, v in r.items() if n != 'conflicts' and v}
                                            for k, r in report.items()},
              'conflicts': {k: r['conflicts'] for k, r in report.items() if r['conflicts']}}
    print(json.dumps(result, ensure_ascii=False))
    if os.access('/rehearsal', os.W_OK):
        with open('/rehearsal/r3-report.json', 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    sys.exit(main())

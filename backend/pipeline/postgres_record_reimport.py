"""The operator's personal records from the MacBook's latest copy, inside the cutover freeze right after the
publication (sync rehearsal R3; rule: architect #3 6944416904).

Three-way per record against the 11-14 base, the state both sides started from: equal; changed only on the MacBook
(applied to the ledger); changed only in the candidate (kept); changed on both sides differently (conflict: the
MacBook's value is applied, the candidate's is archived in candidate_record_archive for the user to review after the
cutover — the freeze never waits). Computed rows (watch evaluations) are marked, since they are evaluated again.
Records match by natural key; content compares the columns both sides keep. A second run finds everything equal.
"""
import hashlib
import json

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

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
COMPUTED = {'owner_legacy_rows[watch_evaluations]'}  # also every owner_row_overrides table but feature_flags (below)


def _computed(name):
    """Rows the system computes (evaluated again after the cutover) rather than the operator's own choices."""
    return name in COMPUTED or (name.startswith('owner_row_overrides[') and name != 'owner_row_overrides[feature_flags]')


def _digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _norm(value):
    return None if value in (None, '') else (int(value) if isinstance(value, bool) else value)


def _exists(db, table):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone() is not None


def _legacy(db, table, key, columns):
    """{key: (digest, row dict)} of a legacy table."""
    if not _exists(db, table):
        return {}
    db_columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
    out = {}
    for row in db.execute(f'SELECT * FROM "{table}"'):
        data = dict(zip(db_columns, row))
        out[tuple(str(data[k]) for k in key)] = (_digest([_norm(data.get(c)) for c in columns]), data)
    return out


def classify(base, candidate, source):
    """{key: kind} for keys not equal on both sides: take_source | keep_candidate | conflict."""
    out = {}
    for key in set(base) | set(candidate) | set(source):
        b, c, s = (side.get(key, (None,))[0] for side in (base, candidate, source))
        if c == s:
            continue
        out[key] = 'take_source' if c == b else 'keep_candidate' if s == b else 'conflict'
    return out


def _sides(pg, base, source):
    """Per ledger: (base, candidate, source) keyed records, and how to write one."""
    from pipeline.postgres_owner_legacy_fixture import TABLES
    sides = {}
    for ledger, table, key, content in LEDGERS:
        have = {row[1] for row in base.execute(f'PRAGMA table_info("{table}")')} if _exists(base, table) else set()
        columns = [c for c in content if c in have]
        b, s = _legacy(base, table, key, columns), _legacy(source, table, key, columns)
        cursor = pg.execute(f'SELECT * FROM "{ledger}"')
        names = [d.name for d in cursor.description]
        c = {}
        for row in cursor:
            data = dict(zip(names, row))
            c[tuple(str(data[k]) for k in key)] = (_digest([_norm(data.get(col)) for col in columns]), data)
        if ledger in CHOICES:
            c = {**b, **c}
        sides[ledger] = (b, c, s, ('ledger', ledger, key, names))
    multiset = lambda rows: {(_digest([_norm(v) for v in row]), n): ('x', dict(zip(TRANSACTIONS, row)))  # noqa: E731
                             for row in set(rows) for n in range(rows.count(row))}
    legacy = lambda db: [tuple(row) for row in db.execute(f'SELECT {",".join(TRANSACTIONS)} FROM portfolio_transactions')]  # noqa: E731
    sides['fixture_portfolio_transactions'] = (
        multiset(legacy(base)), multiset([tuple(row) for row in pg.execute(
            f'SELECT {",".join(TRANSACTIONS)} FROM fixture_portfolio_transactions')]), multiset(legacy(source)),
        ('transactions',))
    # The candidate's overrides of collected or computed rows (operator decisions such as feature flags, and its own
    # computations): the visible row is the override where one exists, the collected row otherwise.
    keys = {}
    for table, column in pg.execute('SELECT table_name, key_column FROM owner_override_keys ORDER BY 1, ctid'):
        keys[table] = column.split('|')  # a composite key is one row, its columns joined by '|'
    for table, in pg.execute('SELECT DISTINCT table_name FROM owner_row_overrides ORDER BY 1').fetchall():
        if table not in keys or not _exists(source, table):
            continue
        have = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
        joined = lambda side: {('|'.join(k),): v for k, v in side.items()}  # noqa: E731
        b, src = joined(_legacy(base, table, tuple(keys[table]), have)), joined(_legacy(source, table, tuple(keys[table]), have))
        candidate = dict(b)
        for key, data in pg.execute('SELECT key, row_data FROM owner_row_overrides WHERE table_name=%s', (table,)):
            if data is None:  # an override without a row removes it
                candidate.pop((key,), None)
            else:
                candidate[(key,)] = (_digest([_norm(data.get(col)) for col in have]), data)
        sides[f'owner_row_overrides[{table}]'] = (b, candidate, src, ('override', table))
    for table in TABLES:
        if not _exists(source, table):
            continue
        have = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
        ledger_rows = {str(pk): data for pk, data in pg.execute(
            'SELECT pk, row_data FROM owner_legacy_rows WHERE table_name=%s AND account_id IS NULL', (table,))}
        columns = sorted(set(have) & set().union(*(d.keys() for d in ledger_rows.values()))) if ledger_rows else sorted(have)
        columns = [c for c in columns if c != 'id']
        pick = lambda db: {(k[0],): v for k, v in _legacy(db, table, ('id',), columns).items()}  # noqa: E731
        c = {(pk,): (_digest([_norm(d.get(col)) for col in columns]), d) for pk, d in ledger_rows.items()}
        sides[f'owner_legacy_rows[{table}]'] = (pick(base), c, pick(source), ('legacy', table))
    return sides


def compare(pg, base, source):
    """Counts per ledger and the conflicting keys (no content)."""
    report = {}
    for name, (b, c, s, _how) in _sides(pg, base, source).items():
        kinds = classify(b, c, s)
        counts = {k: sum(1 for v in kinds.values() if v == k) for k in ('take_source', 'keep_candidate', 'conflict')}
        report[name] = {'same': len(set(b) | set(c) | set(s)) - len(kinds), **counts,
                        'conflicts': sorted(list(k) for k, v in kinds.items() if v == 'conflict'),
                        'computed': _computed(name)}
    return report


def apply(pg, base, source):
    """Apply the MacBook's changes and the conflicts (MacBook value; candidate value archived), one transaction."""
    from pipeline import postgres_owner_legacy_fixture as owner_legacy
    _guard(pg)
    applied = {}
    with pg.transaction():
        pg.execute('CREATE TABLE IF NOT EXISTS candidate_record_archive (id BIGSERIAL PRIMARY KEY, ledger TEXT NOT NULL, '
                   'record_key JSONB NOT NULL, candidate_row JSONB, source_row JSONB, computed BOOLEAN NOT NULL, '
                   "reason TEXT NOT NULL DEFAULT 'conflict: MacBook value applied', archived_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        account = pg.execute('SELECT account_id FROM fixture_portfolio_legacy_mapping').fetchone()[0]
        legacy_changes = []
        for name, (b, c, s, how) in _sides(pg, base, source).items():
            kinds = {k: v for k, v in classify(b, c, s).items() if v in ('take_source', 'conflict')}
            if not kinds:
                continue
            applied[name] = {'take_source': sum(1 for v in kinds.values() if v == 'take_source'),
                             'conflict': sum(1 for v in kinds.values() if v == 'conflict')}
            for key, kind in kinds.items():
                if kind == 'conflict':
                    pg.execute('INSERT INTO candidate_record_archive (ledger, record_key, candidate_row, source_row, computed) '
                               'VALUES (%s,%s,%s,%s,%s)', (name, Jsonb(list(key)), Jsonb(c.get(key, (None, None))[1]),
                                                           Jsonb(s.get(key, (None, None))[1]), _computed(name)))
            if how[0] == 'ledger':
                _, ledger, key_columns, names = how
                for key in kinds:
                    where = ' AND '.join(f'"{k}"::text = %s' for k in key_columns)
                    pg.execute(f'DELETE FROM "{ledger}" WHERE {where}', key)
                    row = s.get(key, (None, None))[1]
                    if row is None:
                        continue  # removed on the MacBook
                    values = {col: row[col] for col in names if col in row and (col != 'id' or 'id' in key_columns)}
                    if 'account_id' in names:
                        values['account_id'] = account
                    columns = ','.join('"%s"' % col for col in values)
                    pg.execute(f'INSERT INTO "{ledger}" ({columns}) '
                               f'VALUES ({",".join(["%s"] * len(values))})', tuple(values.values()))
            elif how[0] == 'transactions':
                for key in kinds:
                    in_source, in_candidate = key in s, key in c
                    row = (s if in_source else c)[key][1]
                    if in_source and not in_candidate:
                        pg.execute(f'INSERT INTO fixture_portfolio_transactions (account_id,{",".join(TRANSACTIONS)}) '
                                   f'VALUES (%s,{",".join(["%s"] * len(TRANSACTIONS))})', (account, *row.values()))
                    elif in_candidate and not in_source:
                        pg.execute('DELETE FROM fixture_portfolio_transactions WHERE ctid = (SELECT ctid FROM '
                                   'fixture_portfolio_transactions WHERE ' +
                                   ' AND '.join(f'"{col}" IS NOT DISTINCT FROM %s' for col in TRANSACTIONS) + ' LIMIT 1)',
                                   tuple(row.values()))
            elif how[0] == 'override':
                table = how[1]
                for key in kinds:
                    row = s.get(key, (None, None))[1]
                    if row is None:  # removed on the MacBook: the candidate's override goes too
                        pg.execute('DELETE FROM owner_row_overrides WHERE table_name=%s AND key=%s', (table, key[0]))
                    else:  # not overridden here: the published MacBook row is already what shows
                        pg.execute('UPDATE owner_row_overrides SET row_data=%s, updated_at=now() '
                                   'WHERE table_name=%s AND key=%s', (Jsonb(row), table, key[0]))
            else:
                table = how[1]
                upserts = {int(k[0]): s[k][1] for k in kinds if k in s}
                deletes = [int(k[0]) for k in kinds if k not in s and k in c]
                legacy_changes.append((table, upserts, deletes))
        if legacy_changes:
            started = pg.execute('SELECT counter FROM owner_legacy_version WHERE singleton').fetchone()[0]
            owner_legacy.apply(pg, started, legacy_changes, {})
    return applied

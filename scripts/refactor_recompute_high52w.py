"""52-week high signals of past days recomputed from corrected prices (after pricefix), reconciled by key.

  python scripts/refactor_recompute_high52w.py <from> <to>            # dry run: what would change, per day
  python scripts/refactor_recompute_high52w.py <from> <to> --apply    # one PG transaction, every change logged

Same rule as pipeline.signals.compute_high_52w, as of each day: the day's high above the highest high of the 365
days before, with at least MIN_HISTORY_ROWS bars up to that day (the original counts bars without an upper bound
because it only ever runs on the latest day). Only days that already have high_52w signals are reconciled: a signal
the corrected prices no longer support is removed, one they newly support is added, a kept one gets the corrected
payload. Run in a job container (PG and the projection); collected_row_history keeps the value before each change.
"""
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refactor_collect_trial as trial  # noqa: E402

SOURCE = 'recompute:high_52w after pricefix (KRX regular session)'
KEY = ('signal_type', 'entity_id', 'date')


def prices(pg, start):
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE p (code TEXT, day TEXT, high REAL, close REAL)')
    conn.executemany('INSERT INTO p VALUES (?,?,?,?)', pg.execute(
        "SELECT row_data->>'stock_code', row_data->>'trade_date', (row_data->>'high')::float, (row_data->>'close')::float "
        "FROM legacy_supplement_rows WHERE table_name='stock_prices' AND row_data->>'trade_date' >= %s", (start,)))
    conn.execute('CREATE INDEX p_code_day ON p (code, day)')
    return conn


def compute(conn, day, entities, min_rows):
    found = {}
    for code, close, high, prior, n in conn.execute('''
            SELECT sp.code, sp.close, sp.high,
                   (SELECT max(q.high) FROM p q WHERE q.code=sp.code AND q.day < sp.day AND q.day >= date(sp.day,'-365 days')),
                   (SELECT count(*) FROM p q WHERE q.code=sp.code AND q.day <= sp.day AND q.day >= date(sp.day,'-365 days'))
            FROM p sp WHERE sp.day=? AND sp.high IS NOT NULL''', (day,)):
        if (n or 0) < min_rows or not prior or high <= prior or code not in entities:
            continue
        payload = {'close': int(close) if close == int(close) else close, 'high': int(high) if high == int(high) else high,
                   'prior_high_52w': int(prior) if prior == int(prior) else prior,
                   'breakout_pct': round((high / prior - 1) * 100, 2)}
        found[entities[code]] = payload
    return found


def main(first, last, apply):
    from pipeline import postgres_isolated_collect as iso
    from pipeline.signals import MIN_HISTORY_ROWS
    pg = trial._pg()
    entities = {row['aliases']: row['id'] for (row,) in pg.execute(
        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entities' AND row_data->>'type'='company' "
        "AND row_data->>'aliases' IS NOT NULL")}
    stored = {}
    for (row,) in pg.execute("SELECT row_data FROM legacy_supplement_rows WHERE table_name='signals' AND "
                             "row_data->>'signal_type'='high_52w' AND row_data->>'date' BETWEEN %s AND %s", (first, last)):
        stored.setdefault(row['date'], {})[row['entity_id']] = row
    start = time.strftime('%Y-%m-%d', time.gmtime(time.mktime(time.strptime(first, '%Y-%m-%d')) - 400 * 86400))
    conn = prices(pg, start)
    top = pg.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0) FROM legacy_supplement_rows WHERE table_name='signals'").fetchone()[0]
    upserts, deletes, report = [], [], {}
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    for day in sorted(stored):
        new = compute(conn, day, entities, MIN_HISTORY_ROWS)
        old = stored[day]
        removed = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        changed = [e for e in set(old) & set(new) if json.loads(old[e]['payload_json']) != new[e]]
        report[day] = {'stored': len(old), 'recomputed': len(new), 'removed': removed, 'added': added, 'payload_changed': len(changed)}
        for e in removed:
            deletes.append(('high_52w', e, day))
        for e in changed:
            upserts.append({**old[e], 'payload_json': json.dumps(new[e], ensure_ascii=False)})
        for e in added:
            top += 1
            upserts.append({'id': top, 'date': day, 'entity_id': e, 'created_at': now, 'signal_type': 'high_52w',
                            'payload_json': json.dumps(new[e], ensure_ascii=False), 'interpretation': None,
                            'interpretation_model': None})
    print(json.dumps({'days': report, 'upserts': len(upserts), 'deletes': len(deletes)}, ensure_ascii=False))
    if apply and (upserts or deletes):
        token = uuid.uuid4().hex
        with pg.transaction():
            applied = iso.apply_keyed(pg, 'signals', KEY, upserts, deletes, history=(SOURCE, 'recompute_high52w', token))
        print(json.dumps({'applied': applied, 'token': token}))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], '--apply' in sys.argv)

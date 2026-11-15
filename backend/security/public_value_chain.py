"""Read prepared market-only value-chain responses from the public snapshot."""
import json
import sqlite3
from pathlib import Path

from config import DB_PATH


def stored(name, kr=None, *, path=None):
    if name not in {'value-chain', 'propagation', 'confirm', 'flow', 'expectations', 'links'}:
        raise ValueError('Unknown snapshot')
    with sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
        conn.execute('PRAGMA query_only=ON')
        row = conn.execute('SELECT payload FROM public_value_chain_snapshot WHERE name=?', (name,)).fetchone()
    if row is None:
        raise LookupError('Snapshot unavailable')
    data = json.loads(row[0])
    if kr and name == 'links':
        data['items'] = [item for item in data['items'] if item['kr_code'] == kr]
    if kr and name == 'confirm':
        data = [item for item in data if item['stock_code'] == kr]
        if not data:
            raise LookupError('Company confirmation unavailable')
    return data


def report(report_id, *, path=None):
    with sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
        conn.execute('PRAGMA query_only=ON')
        row = conn.execute('SELECT payload FROM public_chain_reports WHERE id=?', (report_id,)).fetchone()
    if row is None:
        raise LookupError('Report unavailable')
    return json.loads(row[0])


def reports(root, *, path=None):
    with sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('SELECT payload FROM public_chain_reports WHERE root=? ORDER BY id DESC LIMIT 10', (root,)).fetchall()
    fields = ('id', 'root', 'status', 'outline', 'created_at', 'finished_at')
    return [{k: value.get(k) for k in fields} for value in (json.loads(row[0]) for row in rows)]

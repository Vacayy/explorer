"""Fixed reviewed macro inputs; no private signal cache or lazy collection."""
from pathlib import Path
import math
import os
import json
import re
from fastapi import HTTPException
import sqlite3
from pipeline import macro

# Source review and attribution references: docs/specs/macro.md.
BOARD = 'https://www.federalreserve.gov/releases/{release}/data/FRB_{release}_xml.zip'
NYFED = 'https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/200.json'
SOURCES = {
    'us2y': ('risk_us2y', 'RIFLGFCY02_N.B', 'Board of Governors of the Federal Reserve System', BOARD.format(release='h15')),
    'us10y': ('risk_us10y', 'RIFLGFCY10_N.B', 'Board of Governors of the Federal Reserve System', BOARD.format(release='h15')),
    'fed_bs': ('macro_fed_bs', 'RESPPMA_N.WW', 'Board of Governors of the Federal Reserve System', BOARD.format(release='h41')),
    'tga': ('macro_tga', 'RESPPLLDT_XAW_N.WW', 'Board of Governors of the Federal Reserve System', BOARD.format(release='h41')),
    'm2': ('macro_m2', 'M2.M', 'Board of Governors of the Federal Reserve System', BOARD.format(release='h6')),
    'rrp': ('macro_rrp', 'overnight_treasury_rrp', 'Federal Reserve Bank of New York', NYFED),
}
INPUTS = {'us2y': ('us2y',), 'us10y': ('us10y',), 'm2': ('m2',),
          'net_liq': ('fed_bs', 'tga', 'rrp')}


def _authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    allowed = {'market_indicators': {'indicator','snapshot_date','value'},
               'meta': {'key','value'}, 'source_receipts': {'key','receipt_json'}}
    if action == sqlite3.SQLITE_READ and database == 'main' and column in allowed.get(table, set()):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def macro_connection(path=None):
    selected = path or os.environ.get('EXPLORER_PUBLIC_MACRO_DB')
    if not selected:
        raise HTTPException(503, 'Public macro snapshot is not configured')
    try:
        conn = sqlite3.connect(Path(selected).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    except (OSError, sqlite3.Error, ValueError):
        raise HTTPException(503, 'Public macro snapshot is unavailable') from None
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        conn.set_authorizer(_authorize)
        row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if not row or row[0] != 'public_macro_direct_v1':
            raise ValueError('Not a verified direct-source snapshot')
        return conn
    except (sqlite3.Error, ValueError):
        conn.close()
        raise HTTPException(503, 'Public macro snapshot is unavailable') from None


def stored_macro():
    conn = macro_connection()
    try:
        raw, invalid = {}, set()
        for key, (indicator, series_id, _, source_url) in SOURCES.items():
            receipt_row = conn.execute('SELECT receipt_json FROM source_receipts WHERE key=?', (key,)).fetchone()
            try:
                receipt = json.loads(receipt_row[0]) if receipt_row else {}
            except (TypeError, ValueError):
                receipt = {}
            if (not isinstance(receipt, dict) or not isinstance(receipt.get('sha256'), str)
                    or receipt.get('series_id') != series_id or receipt.get('source_url') != source_url
                    or not re.fullmatch(r'[0-9a-f]{64}', receipt.get('sha256', ''))):
                invalid.add(key); raw[key] = []; continue
            rows = conn.execute('SELECT snapshot_date,value FROM market_indicators WHERE indicator=? ORDER BY snapshot_date DESC LIMIT 70', (indicator,)).fetchall()[::-1]
            if any(not isinstance(r['value'], (int,float)) or not math.isfinite(r['value']) for r in rows):
                invalid.add(key)
                raw[key] = []
            else:
                raw[key] = [(r['snapshot_date'], r['value']) for r in rows]
        numeric = macro.numeric_macro(raw)
        items, coverage = [], []
        values = {item['key']:item for item in numeric['items']}
        for meta in macro.INDICATORS:
            key = meta['key']; inputs = INPUTS.get(key, ())
            status = ('source_review_pending' if not inputs or any(k not in SOURCES for k in inputs)
                      else 'invalid' if any(k in invalid for k in inputs)
                      else 'missing' if key not in values else 'available')
            coverage.append({'key':key, 'label':meta['label'], 'status':status})
            if status != 'available':
                continue
            item = values[key]
            points = item['dated_series']
            sources = [{'series_id':SOURCES[k][1], 'publisher':SOURCES[k][2],
                        'url':SOURCES[k][3],
                        'as_of':raw[k][-1][0] if raw[k] else None} for k in inputs]
            items.append({**item, 'comparison_date':points[-6][0] if len(points)>=6 else None,
                          'comparison_observations':5, 'sources':sources})
        return {'as_of':max((i['as_of'] for i in items),default=None), 'items':items, 'coverage':coverage}
    finally:
        conn.close()

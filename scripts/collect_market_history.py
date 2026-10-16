"""Stage NAVER history and publish a coherent adjusted-price store for analysis.

Collection is a trusted ETL command, separate from the read-only CodeAct runtime.
No init_db, cache helpers, table replacement, or market-cap reconstruction is used.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
COLUMNS = ('open', 'high', 'low', 'close', 'volume')
SELECT = ','.join(COLUMNS)


def valid(values) -> bool:
    if len(values) != 5 or any(v is None or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        return False
    o, high, low, close, volume = values
    return min(o, high, low, close) > 0 and high >= max(o, low, close) and low <= min(o, high, close) and volume >= 0


def readonly(path: Path):
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    connection.execute('PRAGMA query_only=ON')
    return connection


def stage_connection(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / 'staging.sqlite', timeout=30)
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (code TEXT PRIMARY KEY,start TEXT NOT NULL,end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',rows INTEGER DEFAULT 0,invalid INTEGER DEFAULT 0,error TEXT,fetched_at TEXT);
        CREATE TABLE IF NOT EXISTS prices (code TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,
            PRIMARY KEY(code,date));
        CREATE TABLE IF NOT EXISTS issues (code TEXT,date TEXT,reason TEXT,raw TEXT);
    ''')
    return connection


def put_meta(stage, key, value):
    stage.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (key, json.dumps(value, ensure_ascii=False)))
    stage.commit()


def metadata(stage, key):
    row = stage.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def plan(source: Path, folder: Path, days: int = 730):
    with closing(stage_connection(folder)) as stage:
        if metadata(stage, 'source'):
            if metadata(stage, 'source') != str(source.resolve()):
                raise ValueError('Staging source mismatch')
            return
        with closing(readonly(source)) as original:
            original.execute('BEGIN')
            end = original.execute('SELECT max(trade_date) FROM stock_prices').fetchone()[0]
            start = (date.fromisoformat(end) - timedelta(days=days)).isoformat()
            tasks = []
            for code, first_bad in original.execute('''SELECT stock_code,min(CASE WHEN
                open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL
                OR min(open,high,low,close)<=0 OR high<max(open,low,close)
                OR low>min(open,high,close) OR volume<0 THEN trade_date END)
                FROM stock_prices GROUP BY stock_code ORDER BY stock_code'''):
                if not re.fullmatch('[0-9A-Z]{6}', str(code)):
                    continue
                tasks.append((code, min(start, first_bad) if first_bad else start, end))
            stage.executemany('INSERT INTO tasks(code,start,end) VALUES (?,?,?)', tasks)
            put_meta(stage, 'source', str(source.resolve()))
            put_meta(stage, 'as_of', end)
            put_meta(stage, 'start', start)
            put_meta(stage, 'planned_at', datetime.now(timezone.utc).isoformat())
            put_meta(stage, 'policy', 'publish separate coherent NAVER history; original database is read-only')
        print(json.dumps({'phase': 'planned', 'symbols': len(tasks), 'start': start, 'end': end}), flush=True)


def collect(folder: Path):
    import FinanceDataReader as fdr
    import requests
    # FDR's NAVER adapter has no timeout parameter; bound only this ETL process.
    original_request = requests.sessions.Session.request
    def bounded_request(self, *args, **kwargs):
        kwargs.setdefault('timeout', (5, 25))
        return original_request(self, *args, **kwargs)
    requests.sessions.Session.request = bounded_request
    try:
        with closing(stage_connection(folder)) as stage:
            put_meta(stage, 'provider', {'name': 'NAVER', 'reader': 'FinanceDataReader', 'version': fdr.__version__,
                                      'adjustment': 'provider-adjusted; existing source remains mixed/unknown'})
            tasks = stage.execute("SELECT code,start,end FROM tasks WHERE status!='collected' ORDER BY code").fetchall()
            for index, (code, start, end) in enumerate(tasks, 1):
                started = time.monotonic()
                error = None
                for attempt in range(3):
                    try:
                        frame = fdr.DataReader('NAVER:' + code, start, end)
                        if frame.empty:
                            raise ValueError('No provider history in requested range')
                        rows, issues = [], []
                        duplicated = frame.index.duplicated(keep=False)
                        for (stamp, row), duplicate in zip(frame.iterrows(), duplicated):
                            day = stamp.date().isoformat()
                            values = tuple(float(row[name.title()]) for name in COLUMNS)
                            if not start <= day <= end:
                                raise ValueError('Provider date outside requested range')
                            if duplicate or not valid(values):
                                issues.append((code, day, 'duplicate_date' if duplicate else 'invalid_ohlcv',
                                               json.dumps([v if math.isfinite(v) else None for v in values])))
                            else:
                                rows.append((code, day, *values))
                        if not rows:
                            raise ValueError('No valid provider candles')
                        with stage:
                            stage.execute('DELETE FROM prices WHERE code=?', (code,))
                            stage.execute('DELETE FROM issues WHERE code=?', (code,))
                            stage.executemany('INSERT INTO prices VALUES (?,?,?,?,?,?,?)', rows)
                            stage.executemany('INSERT INTO issues VALUES (?,?,?,?)', issues)
                            stage.execute("UPDATE tasks SET status='collected',rows=?,invalid=?,error=NULL,fetched_at=? WHERE code=?",
                                          (len(rows), len(issues), datetime.now(timezone.utc).isoformat(), code))
                        break
                    except Exception as exc:
                        error = f'{type(exc).__name__}: {str(exc)[:300]}'
                        if attempt < 2:
                            time.sleep(1 + attempt)
                else:
                    with stage:
                        stage.execute("UPDATE tasks SET status='failed',error=? WHERE code=?", (error, code))
                    print(json.dumps({'phase': 'fetch_failed', 'code': code, 'error': error}), flush=True)
                if index % 50 == 0 or index == len(tasks):
                    print(json.dumps({'phase': 'collecting', 'done': index, 'total': len(tasks),
                                      'staged_rows': stage.execute('SELECT count(*) FROM prices').fetchone()[0]}), flush=True)
                # At most four provider requests per second, one in flight.
                time.sleep(max(0, .25 - (time.monotonic() - started)))
    finally:
        requests.sessions.Session.request = original_request


def publish(folder: Path, destination: Path):
    """Publish one vendor's entire validated series, never splice price bases.

    Atomic replacement affects only the dedicated derived history file. The
    original stock_explorer.db is never opened for writing in this path.
    """
    if destination.name != 'market_history.sqlite':
        raise ValueError('Publish destination must be the dedicated market_history.sqlite')
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError('Linked destination is not allowed')
    with closing(stage_connection(folder)) as stage:
        if metadata(stage, 'source') == str(destination.resolve()):
            raise ValueError('Cannot publish over the source database')
        if stage.execute("SELECT count(*) FROM tasks WHERE status='pending'").fetchone()[0]:
            raise ValueError('Collection must finish before publishing')
        count = stage.execute('SELECT count(*) FROM prices').fetchone()[0]
        if not count:
            raise ValueError('No validated rows to publish')
        temp = destination.parent / f'.market-history-{uuid.uuid4().hex}.sqlite'
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(temp)) as output:
                output.executescript('''
                    CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE coverage (code TEXT PRIMARY KEY,status TEXT,start TEXT,end TEXT,rows INTEGER,invalid INTEGER);
                    CREATE TABLE prices (code TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,
                                         PRIMARY KEY(code,date));
                ''')
                for key, value in {
                    'schema_version': 1, 'collection_id': folder.name,
                    'as_of': metadata(stage, 'as_of'), 'start': metadata(stage, 'start'),
                    'provider': metadata(stage, 'provider'),
                    'published_at': datetime.now(timezone.utc).isoformat(),
                }.items():
                    output.execute('INSERT INTO metadata VALUES (?,?)', (key, json.dumps(value,ensure_ascii=False)))
                output.executemany('INSERT INTO coverage VALUES (?,?,?,?,?,?)',
                                   stage.execute('SELECT code,status,start,end,rows,invalid FROM tasks'))
                for row in stage.execute('SELECT * FROM prices ORDER BY code,date'):
                    if not valid(row[2:]):
                        raise ValueError('Invalid staged candle; cannot publish')
                    output.execute('INSERT INTO prices VALUES (?,?,?,?,?,?,?)', row)
                output.commit()
                if output.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Published history integrity failed')
            with temp.open('rb') as stream:
                os.fsync(stream.fileno())
            temp.chmod(0o444)
            os.replace(temp, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            put_meta(stage, 'published', {'path': str(destination.resolve()), 'rows': count})
            print(json.dumps({'phase': 'published', 'rows': count, 'path': str(destination)}),flush=True)
        finally:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=PROJECT / 'backend/db/stock_explorer.db')
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--days', type=int, default=730)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--publish', action='store_true', help='publish a separate coherent adjusted history (recommended)')
    args = parser.parse_args()
    if not 500 <= args.days <= 3650:
        parser.error('--days must be between 500 and 3650')
    plan(args.source, args.workdir, args.days)
    if args.collect:
        collect(args.workdir)
    if args.publish:
        publish(args.workdir, args.source.with_name('market_history.sqlite'))


if __name__ == '__main__':
    main()

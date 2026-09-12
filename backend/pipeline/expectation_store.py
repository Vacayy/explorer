"""Experiment-only persistence. No writes or schema initialization in the production DB."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from config import DB_PATH
from models.expectations import StatementFields

EXPERIMENT_DB = Path(DB_PATH).with_name('expectations_experiment.sqlite')


@contextmanager
def connect():
    if Path(EXPERIMENT_DB).resolve() == Path(DB_PATH).resolve():
        raise RuntimeError('실험 DB는 원본 DB와 분리해야 합니다')
    Path(EXPERIMENT_DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(EXPERIMENT_DB, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute('PRAGMA foreign_keys=ON')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL, hash TEXT NOT NULL,
            data TEXT NOT NULL, UNIQUE(doc_id, hash));
          CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
            version TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            error TEXT, result TEXT, usage TEXT);
          CREATE TABLE IF NOT EXISTS statements (
            id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
            job_id TEXT, data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
            revision INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
          CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, statement_id INTEGER NOT NULL REFERENCES statements(id),
            revision INTEGER NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
          CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY, statement_id INTEGER NOT NULL REFERENCES statements(id),
            text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        ''')
        # Local pilot schema evolution only; production DB is never opened here.
        if 'version' not in {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}:
            c.execute("ALTER TABLE jobs ADD COLUMN version TEXT NOT NULL DEFAULT ''")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def snapshot(c, doc):
    c.execute('INSERT OR IGNORE INTO snapshots(doc_id,hash,data) VALUES (?,?,?)',
              (doc.id, doc.text_sha256, doc.model_dump_json()))
    return c.execute('SELECT id FROM snapshots WHERE doc_id=? AND hash=?',
                     (doc.id, doc.text_sha256)).fetchone()['id']


def statement(row):
    d = dict(row)
    d['fields'] = StatementFields.model_validate_json(d.pop('data')).model_dump()
    snap = json.loads(d.pop('snapshot_data'))
    d['document'] = {k: snap[k] for k in ('id','title','source_type','source_id','source_url','published_at','fetched_at','text_sha256','text_kind')}
    return d


STATEMENT_SQL = '''SELECT s.*, p.data snapshot_data FROM statements s
                   JOIN snapshots p ON p.id=s.snapshot_id'''


def list_statements(doc_id=None, status=None):
    where, params = [], []
    if doc_id is not None:
        where.append('p.doc_id=?'); params.append(doc_id)
    if status:
        where.append('s.status=?'); params.append(status)
    with connect() as c:
        rows = c.execute(STATEMENT_SQL + (' WHERE '+' AND '.join(where) if where else '')
                         + ' ORDER BY s.id DESC LIMIT 500', params).fetchall()
    return [statement(r) for r in rows]


def get_statement(sid):
    with connect() as c:
        row = c.execute(STATEMENT_SQL+' WHERE s.id=?',(sid,)).fetchone()
    return statement(row) if row else None


def job(jid):
    with connect() as c:
        # A crashed process cannot leave a permanently pending job in the UI.
        c.execute("""UPDATE jobs SET state='failed',error='작업 시간이 만료됐습니다. 다시 추출하세요.'
                     WHERE state IN ('queued','running') AND julianday('now')-julianday(updated_at)>10.0/1440""")
        row = c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for k in ('result','usage'):
        d[k] = json.loads(d[k]) if d[k] else None
    return d

"""Legacy chunk index (doc_chunks + chunk_fts + chunk_vec) for the single-path candidate's compute worker.

The base snapshot leaves chunks out; this copies them, unchanged, from the base generation's own
backup into a SQLite file beside the projection, so the legacy chunk search and reranked retrieval
(`pipeline.rag.retrieve_docs`) run as they are, with the projection attached for document rows.
Chunks of documents published after the base generation are not in it yet.
"""
import json
import sqlite3
from pathlib import Path

TABLES = ('doc_chunks',)


def _vec(conn):
    import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def build_from_backup(backup_dir, target, *, batch=2000):
    backup = Path(backup_dir)
    manifest = json.loads((backup / 'manifest.json').read_text())
    path = backup / manifest['file']
    if path.stat().st_size != manifest['size_bytes']:
        raise ValueError('Backup file does not match its manifest')
    target = Path(target)
    partial = target.with_suffix('.partial')
    partial.unlink(missing_ok=True)
    source = _vec(sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True))
    out = _vec(sqlite3.connect(partial))
    try:
        ddl = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='doc_chunks'").fetchone()[0]
        out.execute(ddl)
        out.execute(source.execute("SELECT sql FROM sqlite_master WHERE name='chunk_fts'").fetchone()[0])
        out.execute(source.execute("SELECT sql FROM sqlite_master WHERE name='chunk_vec'").fetchone()[0])
        counts = {}
        for name, select, insert in (
                ('doc_chunks', 'SELECT * FROM doc_chunks ORDER BY id', None),
                ('chunk_fts', 'SELECT rowid,prefix,text FROM chunk_fts ORDER BY rowid', 'INSERT INTO chunk_fts(rowid,prefix,text) VALUES (?,?,?)'),
                ('chunk_vec', 'SELECT rowid,embedding FROM chunk_vec ORDER BY rowid', 'INSERT INTO chunk_vec(rowid,embedding) VALUES (?,?)')):
            cursor = source.execute(select)
            if insert is None:
                columns = [c[0] for c in cursor.description]
                insert = f'INSERT INTO {name} ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})'
            counts[name] = 0
            while rows := cursor.fetchmany(batch):
                out.executemany(insert, rows)
                counts[name] += len(rows)
            out.commit()
        for (sql,) in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='doc_chunks' AND sql IS NOT NULL"):
            out.execute(sql)
        out.commit()
    finally:
        source.close()
        out.close()
    partial.replace(target)
    return counts

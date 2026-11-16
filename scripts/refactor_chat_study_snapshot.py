"""Capture chat/study tables from one read transaction for an isolated PG import.

This is a scoped rehearsal backup, not a full application backup or cutover.
The original SQLite database and its full backups must remain available.
"""
import os
from pathlib import Path
import sqlite3
import sys

from pipeline.postgres_study_fixture import CHAT_COLUMNS, TABLES


def main():
    if os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1':
        raise ValueError('Disposable rehearsal required')
    source_path, target_path = map(Path, sys.argv[1:])
    if not source_path.is_absolute() or not target_path.is_absolute() or target_path.exists():
        raise ValueError('Existing source and new absolute destination required')
    source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(target_path)
    os.chmod(target_path, 0o600)
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        target.execute('PRAGMA foreign_keys=OFF')
        target.execute('BEGIN')
        counts = {}
        for name in (*CHAT_COLUMNS, *TABLES):
            definition = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if not definition or not definition[0]:
                raise ValueError('Missing source table: ' + name)
            target.execute(definition[0])
            columns = [row[1] for row in source.execute('PRAGMA table_info(' + name + ')')]
            rows = source.execute('SELECT * FROM ' + name)
            count = 0
            while batch := rows.fetchmany(500):
                target.executemany('INSERT INTO ' + name + ' VALUES (' + ','.join('?' for _ in columns) + ')', batch)
                count += len(batch)
            counts[name] = count
        target.execute('CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,url TEXT,title TEXT,published_at TEXT)')
        rows = source.execute('SELECT id,source_type,url,title,published_at FROM raw_documents')
        while batch := rows.fetchmany(500):
            target.executemany('INSERT INTO raw_documents VALUES (?,?,?,?,?)', batch)
        if source.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() and target.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            for name, seq in source.execute('SELECT name,seq FROM sqlite_sequence'):
                if name in CHAT_COLUMNS or name in TABLES:
                    target.execute('DELETE FROM sqlite_sequence WHERE name=?', (name,))
                    target.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (name, seq))
        target.commit()
        if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Scoped backup integrity check failed')
        print('Scoped chat/study snapshot verified; tables:', len(counts))
    finally:
        source.close()
        target.close()


if __name__ == '__main__':
    main()

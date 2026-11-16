"""Make a scoped, consistent question-tracker rehearsal snapshot.

This is neither a full application backup nor a final migration snapshot.
The source is read in one SQLite transaction; no source writer is stopped.
"""
import os
from pathlib import Path
import sqlite3
import sys


TABLES = ('questions', 'sub_questions', 'question_reports', 'proxy_registry',
          'proxy_observations', 'proxy_scans', 'proxy_boards', 'proxy_board_items',
          'scenarios', 'observations')


def main():
    if os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1':
        raise ValueError('Disposable rehearsal required')
    source_path, target_path = map(Path, sys.argv[1:])
    if not source_path.is_absolute() or not target_path.is_absolute():
        raise ValueError('Absolute paths required')
    fd = os.open(target_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = target = None
    success = False
    try:
        source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(target_path)
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        target.execute('PRAGMA foreign_keys=OFF')
        target.execute('BEGIN')
        counts = {}
        for table in TABLES:
            definition = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not definition or not definition[0]:
                raise ValueError('Missing source table: ' + table)
            target.execute(definition[0])
            columns = source.execute('PRAGMA table_info(' + table + ')').fetchall()
            cursor = source.execute('SELECT * FROM ' + table)
            count = 0
            while batch := cursor.fetchmany(500):
                target.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in columns) + ')', batch)
                count += len(batch)
            counts[table] = count
        if (source.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() and
                target.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone()):
            for name, seq in source.execute('SELECT name,seq FROM sqlite_sequence'):
                if name in TABLES:
                    target.execute('DELETE FROM sqlite_sequence WHERE name=?', (name,))
                    target.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (name, seq))
        target.commit()
        if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Scoped snapshot integrity check failed')
        success = True
        print('Scoped question snapshot verified:', counts)
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        if not success:
            target_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

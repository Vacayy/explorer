"""Durable, fair staging for fetched feed documents; publication and acknowledgement are separate."""
import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import asdict
from pathlib import Path

from pipeline.base import RawDoc


def stage_one_reference(queue, name, connector):
    """Fetch one rotating reference; a failed fetch or enqueue must not advance its cursor."""
    ref = queue.next_ref(name, connector.discover())
    if ref is None:
        return 0
    count = 0
    for doc in connector.fetch(ref):
        queue.enqueue(name, ref.key, doc)
        count += 1
    queue.advance_ref(name, ref)
    return count


class FeedBacklog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600) if not self.path.exists() else None
        if fd is not None:
            os.close(fd)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Feed backlog must be a private regular file')
        self.conn = sqlite3.connect(self.path)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS pending (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                lane TEXT NOT NULL, connector TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(source_type, source_id)
            );
            CREATE TABLE IF NOT EXISTS feed_cursor (singleton INTEGER PRIMARY KEY CHECK(singleton=1), lane TEXT);
            INSERT OR IGNORE INTO feed_cursor(singleton, lane) VALUES (1, NULL);
            CREATE TABLE IF NOT EXISTS source_cursor (connector TEXT PRIMARY KEY, ref_hash TEXT NOT NULL);
        ''')
        self.conn.commit()

    def close(self):
        self.conn.close()

    def next_ref(self, connector, refs):
        """Select one reference per source, rotating across runs without storing its private key."""
        keyed = sorted({hashlib.sha256(ref.key.encode()).hexdigest(): ref for ref in refs}.items())
        if not keyed:
            return None
        row = self.conn.execute('SELECT ref_hash FROM source_cursor WHERE connector=?', (connector,)).fetchone()
        last = row[0] if row else ''
        return next((ref for key, ref in keyed if key > last), keyed[0][1])

    def advance_ref(self, connector, ref):
        """Advance only after every returned document was durably staged."""
        key = hashlib.sha256(ref.key.encode()).hexdigest()
        with self.conn:
            self.conn.execute('INSERT INTO source_cursor VALUES (?,?) ON CONFLICT(connector) '
                              'DO UPDATE SET ref_hash=excluded.ref_hash', (connector, key))

    def enqueue(self, connector, ref, doc):
        """Keep the latest fetched payload without moving an already waiting document to the back."""
        if not connector or not ref or not doc.source_type or not doc.source_id:
            raise ValueError('Feed document and source identities are required')
        lane = hashlib.sha256((connector + '\0' + ref).encode()).hexdigest()
        payload = json.dumps(asdict(doc), ensure_ascii=False, separators=(',', ':'))
        self.conn.execute('INSERT INTO pending(source_type,source_id,lane,connector,payload) VALUES (?,?,?,?,?) '
                          'ON CONFLICT(source_type,source_id) DO UPDATE SET payload=excluded.payload',
                          (doc.source_type, doc.source_id, lane, connector, payload))
        self.conn.commit()  # fetched material survives a later source failure

    def next(self):
        """Oldest document in the next nonempty source lane, rotating between lanes."""
        last = self.conn.execute('SELECT lane FROM feed_cursor WHERE singleton=1').fetchone()[0] or ''
        lane = self.conn.execute('SELECT lane FROM pending WHERE lane>? GROUP BY lane ORDER BY lane LIMIT 1',
                                 (last,)).fetchone()
        if lane is None:
            lane = self.conn.execute('SELECT lane FROM pending GROUP BY lane ORDER BY lane LIMIT 1').fetchone()
        if lane is None:
            return None
        seq, connector, payload = self.conn.execute('SELECT seq,connector,payload FROM pending WHERE lane=? ORDER BY seq LIMIT 1', lane).fetchone()
        return seq, connector, RawDoc(**json.loads(payload))

    def acknowledge(self, seq):
        """Call only after publication succeeds; deleting and advancing the cursor are atomic."""
        with self.conn:
            row = self.conn.execute('SELECT lane FROM pending WHERE seq=?', (seq,)).fetchone()
            if row is None:
                raise ValueError('Unknown pending document')
            self.conn.execute('DELETE FROM pending WHERE seq=?', (seq,))
            self.conn.execute('UPDATE feed_cursor SET lane=? WHERE singleton=1', (row[0],))

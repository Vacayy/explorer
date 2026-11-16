"""Read-only SQLite projection of one PG candidate for unchanged legacy read routes.

Legacy home, macro and search read many tables through `database.get_connection`.
Instead of re-implementing them, this writes every `legacy_snapshot_tables` row
(base, overlays and same-generation supplement) into one SQLite file inside a
single repeatable-read transaction, and hands legacy code read-only connections.
A changed overlay triggers a background rebuild; readers keep the previous file
until the new one is complete, so they never see a half-built projection.
"""
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from pipeline.postgres_graph_fixture import _guard

# PG-native ledgers that replaced a legacy table; legacy reads must see their rows.
NATIVE = ('study_projects',)
CHECK_SECONDS = 10


class LegacyProjection:
    def __init__(self, factory, directory):
        self.factory = factory
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        for stale in (*self.directory.glob('projection-*.db'), *self.directory.glob('current*')):
            stale.unlink()  # a previous process's files are never reused
        self.lock = threading.Lock()
        self.current = None  # (path, version)
        self.building = False
        self.checked = 0.0

    def _version(self, pg):
        # Cumulative tuple changes of writable overlays; stats lag slightly, rebuilds follow.
        changes = pg.execute("SELECT coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) FROM pg_stat_user_tables "
                             "WHERE schemaname=current_schema()").fetchone()[0]
        generation = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0]
        return f'{generation}:{changes}'

    def _build(self):
        path = self.directory / f'projection-{uuid.uuid4().hex}.db'
        root = sqlite3.connect(path)
        try:
            root.execute('PRAGMA journal_mode=OFF')
            root.execute('PRAGMA synchronous=OFF')
            with self.factory() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                _guard(pg)
                version = self._version(pg)
                tables = pg.execute('SELECT table_name,columns,schema_sql FROM legacy_snapshot_tables ORDER BY table_name').fetchall()
                for name, columns, ddl in tables:
                    root.execute(ddl)
                    actual = [row[1] for row in root.execute(f'PRAGMA table_info("{name}")')]
                    if actual != columns:
                        raise ValueError(f'Projection schema mismatch: {name}')
                    quoted = ','.join('"' + column.replace('"', '""') + '"' for column in columns)
                    insert = f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})'
                    with pg.cursor(name=f'p{uuid.uuid4().hex}') as cursor:
                        cursor.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal', (name,))
                        root.executemany(insert, (tuple(row[0].get(column) for column in columns) for row in cursor))
                from pipeline.study_projects import SCHEMA
                root.executescript(SCHEMA)
                for name in NATIVE:
                    columns = [row[1] for row in root.execute(f'PRAGMA table_info("{name}")')]
                    quoted = ','.join('"' + column + '"' for column in columns)
                    rows = pg.execute(f'SELECT {quoted} FROM {name}').fetchall()
                    root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})', rows)
                for (sql,) in pg.execute('SELECT sql FROM legacy_snapshot_indexes'):
                    root.execute(sql)
            root.commit()
            root.execute('ANALYZE')
            root.close()
            os.chmod(path, 0o400)
            return path, version
        except BaseException:
            root.close()
            path.unlink(missing_ok=True)
            raise

    def _refresh(self):
        try:
            built = self._build()
        except Exception:
            built = None
        with self.lock:
            self.building = False
            if built:
                previous, self.current = self.current, built
                self._link(built[0])
                # Open readers keep the unlinked file until they close.
                if previous:
                    previous[0].unlink(missing_ok=True)

    @property
    def stable_path(self):
        """Fixed name for legacy code that opens `database.DB_PATH` itself."""
        return self.directory / 'current.db'

    def _link(self, path):
        temporary = self.directory / f'current-{uuid.uuid4().hex}'
        temporary.symlink_to(path.name)
        os.replace(temporary, self.stable_path)

    def path(self):
        with self.lock:
            current = self.current
        if current is None:
            with self.lock:
                if self.current is None:
                    self.current = self._build()
                    self._link(self.current[0])
                return self.current[0]
        now = time.monotonic()
        if now - self.checked >= CHECK_SECONDS:
            self.checked = now
            with self.factory() as pg:
                stale = self._version(pg) != current[1]
            with self.lock:
                if stale and not self.building:
                    self.building = True
                    threading.Thread(target=self._refresh, daemon=True).start()
        return current[0]

    def connect(self):
        conn = sqlite3.connect(f'file:{self.path()}?mode=ro', uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn

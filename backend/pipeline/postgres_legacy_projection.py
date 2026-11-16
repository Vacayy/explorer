"""Read-only SQLite projection of one PG candidate for unchanged legacy read routes.

Legacy home, macro and search read many tables through `database.get_connection`.
Instead of re-implementing them, this writes every `legacy_snapshot_tables` row
(base, overlays and same-generation supplement) into one SQLite file inside a
single repeatable-read transaction, and hands legacy code read-only connections.
A changed overlay triggers a background rebuild; readers keep the previous file
until the new one is complete, so they never see a half-built projection.
Document bodies are kept in full: `get_connection` is replaced process-wide, so
any legacy reader in this process must see the same text as the PG reader.
"""
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from contextvars import ContextVar

from pipeline import postgres_owner_legacy_fixture as owner_legacy
from pipeline.postgres_graph_fixture import _guard

# The one connection a legacy write request may use (see postgres_owner_legacy_router).
write_connection_var = ContextVar('legacy_write_connection', default=None)

# PG-native ledgers that replaced a legacy table; legacy reads must see their rows.
NATIVE = ('study_projects', 'questions', 'sub_questions')
# Everything the projection reads that can change after the base load.
VERSIONED = ('video_digest_overlay_rows', 'video_projection_overrides', 'question_graph_overlay_rows',
             'legacy_supplement_tables', 'legacy_supplement_rows', *NATIVE,
             'fixture_portfolio_transactions', 'fixture_portfolio_members', 'fixture_portfolio_principles',
             'owner_follows', 'owner_kalshi_pins', 'owner_channel_reads',
             'owner_saved_items', 'owner_tracker_conditions', 'owner_legacy_rows',
             'owner_transcript_pins', 'owner_transcript_additions', 'owner_knowledge_reviews', 'owner_trade_follow')
# Small owner-ledger tables re-derived per connection in TEMP shadows, so writes
# show at once; the file keeps its own (possibly older) derived copy underneath.
SHADOWED = ('portfolio_transactions', 'stock_group_members', 'stock_groups', 'watch_rules', 'watch_evaluations', 'portfolio_principles', 'follows', 'kalshi_pins', 'channel_reads',
            'saved_items', 'tracker_conditions', 'transcript_follow', 'knowledge', 'trade_follow', *NATIVE)
CHECK_SECONDS = 10
log = logging.getLogger(__name__)


def initialize_projection_version(target):
    """One counter row bumped by statement triggers on every table the projection reads."""
    _guard(target)
    schema = target.execute('SELECT quote_ident(current_schema())').fetchone()[0]
    with target.transaction():
        if target.execute("SELECT to_regclass('legacy_projection_version')").fetchone()[0] is not None:
            raise ValueError('Projection version already initialized')
        target.execute('CREATE TABLE legacy_projection_version (singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK(singleton),'
                       'counter BIGINT NOT NULL)')
        target.execute('INSERT INTO legacy_projection_version VALUES (true,0)')
        target.execute(f'CREATE FUNCTION legacy_projection_bump() RETURNS trigger LANGUAGE plpgsql AS '
                       f'$$BEGIN UPDATE {schema}.legacy_projection_version SET counter=counter+1; RETURN NULL; END$$')
    ensure_projection_triggers(target)


def ensure_projection_triggers(target):
    """Add the counter trigger to versioned tables that do not have it yet."""
    _guard(target)
    with target.transaction():
        for table in VERSIONED:
            if target.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0] is None:
                continue  # e.g. no portfolio ledger in this schema yet
            if not target.execute("SELECT 1 FROM pg_trigger WHERE tgname='legacy_projection_bump' AND tgrelid=to_regclass(%s)",
                                  (table,)).fetchone():
                target.execute(f'CREATE TRIGGER legacy_projection_bump AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} '
                               'FOR EACH STATEMENT EXECUTE FUNCTION legacy_projection_bump()')


class LegacyProjection:
    def __init__(self, factory, directory, *, on_change=None):
        self.factory = factory
        self.on_change = on_change  # called after a rebuild caused by a ledger/overlay change
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        for stale in (*self.directory.glob('projection-*.db'), *self.directory.glob('current*')):
            stale.unlink()  # a previous process's files are never reused
        self.lock = threading.Lock()
        self.current = None  # (path, version)
        self.building = False
        self.failures = 0
        self.legacy_cache = None  # (version, rows, sequences) of the owner legacy ledger

    def _version(self, pg):
        changes = pg.execute('SELECT counter FROM legacy_projection_version WHERE singleton').fetchone()[0]
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
                for name in NATIVE:
                    # Same column names as the legacy table; SQLite keeps each value's own type.
                    columns = [row[0] for row in pg.execute('SELECT column_name FROM information_schema.columns WHERE '
                                                            'table_schema=current_schema() AND table_name=%s '
                                                            'ORDER BY ordinal_position', (name,))]
                    quoted = ','.join('"' + column + '"' for column in columns)
                    root.execute(f'CREATE TABLE "{name}" ({quoted}, PRIMARY KEY("id"))')
                    rows = pg.execute(f'SELECT {quoted} FROM {name}').fetchall()
                    root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})', rows)
                legacy_version = None
                if pg.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is not None:
                    legacy_version, rows, _ = owner_legacy.load(pg)
                    _derive_owner_legacy(root, pg, rows)
                _derive_owner_portfolio(root, pg)
                _derive_owner_records(root, pg)
                for (sql,) in pg.execute('SELECT sql FROM legacy_snapshot_indexes'):
                    root.execute(sql)
            root.commit()
            root.execute('ANALYZE')
            root.close()
            os.chmod(path, 0o400)
            return path, version, legacy_version
        except BaseException:
            root.close()
            path.unlink(missing_ok=True)
            raise

    def _refresh(self):
        try:
            built = self._build()
            self.failures = 0
        except Exception as exc:
            built = None
            self.failures += 1
            # The previous projection keeps serving; say so instead of going silently stale.
            log.warning('Legacy projection rebuild failed (%s, %d in a row); serving the previous one',
                        type(exc).__name__, self.failures)
        with self.lock:
            self.building = False
            if built:
                previous, self.current = self.current, built
                self._link(built[0])
                # Open readers keep the unlinked file until they close.
                if previous:
                    previous[0].unlink(missing_ok=True)
        if built and self.on_change is not None:
            try:
                self.on_change()
            except Exception as exc:
                log.warning('Legacy projection change hook failed (%s)', type(exc).__name__)

    @property
    def stable_path(self):
        """Fixed name for legacy code that opens `database.DB_PATH` itself."""
        return self.directory / 'current.db'

    def _link(self, path):
        temporary = self.directory / f'current-{uuid.uuid4().hex}'
        temporary.symlink_to(path.name)
        os.replace(temporary, self.stable_path)

    def _check(self):
        with self.lock:
            current = self.current
        with self.factory() as pg:
            stale = self._version(pg) != current[1]
        with self.lock:
            if stale and not self.building:
                self.building = True
                threading.Thread(target=self._refresh, daemon=True).start()

    def _poll(self):
        # Writes show within one check plus one rebuild, whether or not anyone reads.
        while True:
            time.sleep(CHECK_SECONDS)
            try:
                self._check()
            except Exception as exc:
                log.warning('Legacy projection version check failed (%s)', type(exc).__name__)

    def path(self):
        with self.lock:
            if self.current is None:
                self.current = self._build()
                self._link(self.current[0])
                threading.Thread(target=self._poll, daemon=True, name='legacy-projection-poll').start()
            return self.current[0]

    def _owner_legacy(self, pg):
        if pg.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is None:
            return None
        version = pg.execute('SELECT counter FROM owner_legacy_version WHERE singleton').fetchone()[0]
        with self.lock:
            cached = self.legacy_cache
        if cached is None or cached[0] != version:
            cached = owner_legacy.load(pg)  # same snapshot as the version just read
            with self.lock:
                self.legacy_cache = cached
        return cached

    def _shadow(self, conn, *, writable=False):
        """TEMP names shadow main ones; the unchanged derivations then write only the shadows."""
        with self.factory() as pg:
            pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            legacy = self._owner_legacy(pg)
            ddl = dict(pg.execute('SELECT table_name,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',
                                  (list(owner_legacy.TABLES),)).fetchall()) if writable else {}
            # The file already holds this ledger version: skip re-deriving its large evaluation table.
            current = self.current
            fresh = not writable and legacy is not None and current is not None and current[2] == legacy[0]
            skip = {'watch_evaluations'} if fresh else set()
            for table in SHADOWED:
                if table in skip:
                    continue
                if table in ddl:
                    # Original DDL keeps PKs, AUTOINCREMENT and cascades for the legacy writer.
                    conn.execute(re.sub(r'^\s*CREATE\s+TABLE\s+', 'CREATE TEMP TABLE ', ddl[table], flags=re.I))
                    conn.execute(f'INSERT INTO temp."{table}" SELECT * FROM main."{table}"')
                else:
                    conn.execute(f'CREATE TEMP TABLE "{table}" AS SELECT * FROM main."{table}"')
                # Same index names, so legacy `CREATE INDEX IF NOT EXISTS` stays a no-op under query_only.
                for (sql,) in conn.execute("SELECT sql FROM main.sqlite_master WHERE type='index' AND tbl_name=? "
                                           "AND sql IS NOT NULL", (table,)).fetchall():
                    conn.execute(re.sub(r'^CREATE\s+(UNIQUE\s+)?INDEX\s+(IF\s+NOT\s+EXISTS\s+)?',
                                        r'CREATE \1INDEX IF NOT EXISTS temp.', sql, flags=re.I))
            if legacy:
                _derive_owner_legacy(conn, pg, legacy[1], skip=skip)
            _derive_owner_portfolio(conn, pg)
            _derive_owner_records(conn, pg)
            _derive_native(conn, pg)
            if writable and legacy:
                for table, seq in legacy[2].items():
                    # Never hand out an ID the legacy writer already used.
                    conn.execute('DELETE FROM temp.sqlite_sequence WHERE name=?', (table,))
                    conn.execute('INSERT INTO temp.sqlite_sequence(name,seq) VALUES (?,?)', (table, seq))
            return legacy[0] if legacy else None

    def connect(self):
        borrowed = write_connection_var.get()
        if borrowed is not None:
            return borrowed
        conn = sqlite3.connect(f'file:{self.path()}?mode=ro', uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            self._shadow(conn)
        except BaseException:
            conn.close()
            raise
        conn.execute('PRAGMA query_only=ON')
        return conn

    def write_connection(self):
        """A projection connection whose owner tables are writable TEMP copies, with the ledger version."""
        conn = sqlite3.connect(f'file:{self.path()}?mode=ro', uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            version = self._shadow(conn, writable=True)
            if version is None:
                raise LookupError('Owner legacy ledger unavailable')
        except BaseException:
            conn.close()
            raise
        conn.commit()  # PRAGMA foreign_keys is ignored inside the transaction the shadow inserts opened
        conn.execute('PRAGMA foreign_keys=ON')  # as legacy get_connection, so group deletes cascade
        if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            conn.close()
            raise RuntimeError('Foreign keys could not be enabled')
        return conn, version


def _derive_native(root, pg):
    """Current rows of the PG-native ledgers (questions, study projects), so new ones show at once."""
    for name in NATIVE:
        columns = [row[1] for row in root.execute(f'PRAGMA table_info("{name}")')]
        quoted = ','.join('"' + column + '"' for column in columns)
        root.execute(f'DELETE FROM "{name}"')
        root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})',
                         pg.execute(f'SELECT {quoted} FROM {name}').fetchall())


def _derive_owner_legacy(root, pg, rows, *, skip=()):
    """Show the owner legacy ledger (groups and their rules/evaluations) through the legacy tables."""
    group = owner_legacy.portfolio_group(pg)
    for table in owner_legacy.TABLES:
        if table in skip:
            continue
        columns = [row[1] for row in root.execute(f'PRAGMA table_info("{table}")')]
        if table == 'stock_group_members':
            root.execute('DELETE FROM stock_group_members WHERE group_id IS NOT ?', (group,))
        else:
            root.execute(f'DELETE FROM "{table}"')
        quoted = ','.join('"' + column + '"' for column in columns)
        root.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({",".join("?" for _ in columns)})',
                         (tuple(row.get(column) for column in columns) for row in rows[table]))


def _derive_owner_portfolio(root, pg):
    """Show the mapped owner's PG ledger through the legacy portfolio tables.

    Mirrors the legacy writer: the group's transactions and principles come from
    the ledger, held members are upserted by bought_at and others removed.
    """
    if pg.execute("SELECT to_regclass('fixture_portfolio_legacy_mapping')").fetchone()[0] is None:
        return
    for group, account in pg.execute('SELECT legacy_group_id,account_id FROM fixture_portfolio_legacy_mapping').fetchall():
        created = dict(root.execute('SELECT id,created_at FROM portfolio_transactions WHERE group_id=?', (group,)))
        root.execute('DELETE FROM portfolio_transactions WHERE group_id=?', (group,))
        root.executemany('INSERT INTO portfolio_transactions (id,group_id,trade_date,kind,stock_code,amount,price,note,created_at) '
                         'VALUES (?,?,?,?,?,?,?,?,?)',
                         [(ident, group, day, kind, code, amount, price, note, created.get(ident))
                          for ident, day, kind, code, amount, price, note in pg.execute(
                              'SELECT id,trade_date,kind,stock_code,amount,price,note FROM fixture_portfolio_transactions '
                              'WHERE account_id=%s ORDER BY id', (account,))])
        held = dict(pg.execute('SELECT stock_code,bought_at FROM fixture_portfolio_members WHERE account_id=%s', (account,)))
        for code, bought in held.items():
            if not root.execute('UPDATE stock_group_members SET bought_at=? WHERE group_id=? AND stock_code=?',
                                (bought, group, code)).rowcount:
                root.execute('INSERT INTO stock_group_members (group_id,stock_code,bought_at) VALUES (?,?,?)', (group, code, bought))
        root.execute('DELETE FROM stock_group_members WHERE group_id=?' +
                     (f' AND stock_code NOT IN ({",".join("?" * len(held))})' if held else ''), (group, *held))
        root.execute('DELETE FROM portfolio_principles')
        root.executemany('INSERT INTO portfolio_principles (id,text,rules_json,created_at,notes_json) VALUES (?,?,?,?,?)',
                         pg.execute('SELECT id,text,rules_json,created_at,notes_json FROM fixture_portfolio_principles '
                                    'WHERE account_id=%s ORDER BY id', (account,)).fetchall())


def _derive_owner_records(root, pg):
    """Show the mapped owner's follows and prediction pins through the legacy tables."""
    if pg.execute("SELECT to_regclass('owner_follows')").fetchone()[0] is None:
        return
    root.execute('DELETE FROM follows')
    root.executemany('INSERT INTO follows (id,entity_id,created_at) VALUES (?,?,?)',
                     pg.execute('SELECT id,entity_id,created_at FROM owner_follows ORDER BY id').fetchall())
    root.execute('DELETE FROM kalshi_pins')
    root.executemany('INSERT INTO kalshi_pins (event_ticker,series_ticker,pinned_at) VALUES (?,?,?)',
                     pg.execute('SELECT event_ticker,series_ticker,pinned_at FROM owner_kalshi_pins').fetchall())
    if pg.execute("SELECT to_regclass('owner_channel_reads')").fetchone()[0] is not None:
        root.execute('DELETE FROM channel_reads')
        root.executemany('INSERT INTO channel_reads (channel,read_until,updated_at) VALUES (?,?,?)',
                         pg.execute('SELECT channel,read_until,updated_at FROM owner_channel_reads').fetchall())
    if pg.execute("SELECT to_regclass('owner_saved_items')").fetchone()[0] is not None:
        root.execute('DELETE FROM saved_items')
        root.executemany('INSERT INTO saved_items (id,kind,ref,url,title,subtitle,note,created_at) VALUES (?,?,?,?,?,?,?,?)',
                         pg.execute('SELECT id,kind,ref,url,title,subtitle,note,created_at FROM owner_saved_items ORDER BY id').fetchall())
    if pg.execute("SELECT to_regclass('owner_tracker_conditions')").fetchone()[0] is not None:
        root.execute('DELETE FROM tracker_conditions')
        root.executemany('INSERT INTO tracker_conditions (id,stock_code,role,kind,level,ma,label,note,done,created_at,updated_at) '
                         'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         pg.execute('SELECT id,stock_code,role,kind,level,ma,label,note,done,created_at,updated_at '
                                    'FROM owner_tracker_conditions ORDER BY id').fetchall())
    derive_owner_transcript_follow(root, pg)
    if pg.execute("SELECT to_regclass('owner_knowledge_reviews')").fetchone()[0] is not None:
        # Operator decisions win over whatever the collector judged for the same knowledge.
        root.executemany('UPDATE knowledge SET review_status=?,epistemic_status=COALESCE(?,epistemic_status) WHERE id=?',
                         pg.execute('SELECT review_status,epistemic_status,knowledge_id FROM owner_knowledge_reviews').fetchall())
    if pg.execute("SELECT to_regclass('owner_trade_follow')").fetchone()[0] is not None:
        # The owner's on/off wins (a collector re-seed would switch items back on); names stay the collector's.
        for hs, name, group, active, updated in pg.execute(
                'SELECT hs_code,item_name,group_label,active,updated_at FROM owner_trade_follow'):
            if root.execute('UPDATE trade_follow SET active=? WHERE hs_code=?', (active, hs)).rowcount == 0:
                root.execute('INSERT INTO trade_follow (hs_code,item_name,group_label,active,added_at) VALUES (?,?,?,?,?)',
                             (hs, name, group, active, updated))


def derive_owner_transcript_follow(root, pg):
    """Collected call-follow rows stay; the owner's follow requests and core pins go over them."""
    if pg.execute("SELECT to_regclass('owner_transcript_pins')").fetchone()[0] is None:
        return
    for ticker, name, group, active, added in pg.execute(
            'SELECT ticker,company_name,group_label,active,added_at FROM owner_transcript_additions'):
        if root.execute('UPDATE transcript_follow SET active=?,company_name=COALESCE(?,company_name),'
                        'group_label=COALESCE(?,group_label) WHERE ticker=?', (active, name, group, ticker)).rowcount == 0:
            root.execute('INSERT INTO transcript_follow (ticker,company_name,group_label,active,added_at) VALUES (?,?,?,?,?)',
                         (ticker, name, group, active, added))
    root.execute('UPDATE transcript_follow SET core_pinned=0')
    root.executemany('UPDATE transcript_follow SET core_pinned=? WHERE ticker=?',
                     pg.execute('SELECT core_pinned,ticker FROM owner_transcript_pins').fetchall())

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
import json
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
NATIVE = ('study_projects', 'questions', 'sub_questions', 'proxy_registry', 'proxy_observations', 'proxy_boards',
          'proxy_board_items')
# PG-native ledgers shown only in the projection file (read by legacy reads in the worker, e.g. the chat's study
# tool); too large to re-derive on every connection, so they show from the next build.
NATIVE_FILE_ONLY = ('study_project_members', 'study_sessions', 'study_annotations')
# Everything the projection reads that can change after the base load.
VERSIONED = ('video_digest_overlay_rows', 'video_projection_overrides', 'question_graph_overlay_rows',
             'legacy_supplement_tables', 'legacy_supplement_rows', *NATIVE, *NATIVE_FILE_ONLY,
             'fixture_portfolio_transactions', 'fixture_portfolio_members', 'fixture_portfolio_principles',
             'owner_follows', 'owner_kalshi_pins', 'owner_channel_reads',
             'owner_saved_items', 'owner_tracker_conditions', 'owner_legacy_rows',
             'owner_transcript_pins', 'owner_transcript_additions', 'owner_knowledge_reviews', 'owner_trade_follow',
             'collected_row_revisions', 'owner_narrative_decisions', 'owner_source_settings',
             'owner_source_additions', 'owner_row_overrides', 'candidate_job_runs')
# Small owner-ledger tables re-derived per connection in TEMP shadows, so writes
# show at once; the file keeps its own (possibly older) derived copy underneath.
SHADOWED = ('portfolio_transactions', 'stock_group_members', 'stock_groups', 'watch_rules', 'watch_evaluations', 'portfolio_principles', 'follows', 'kalshi_pins', 'channel_reads',
            'saved_items', 'tracker_conditions', 'transcript_follow', 'knowledge', 'trade_follow', 'narrative_candidates',
            'telegram_channels', 'blog_sources', 'youtube_channels',
            'industry_groups', 'industry_members', 'business_segments', 'ir_notes',
            'feature_flags', 'era_checks', 'research_candidates', 'agent_proposals', 'entity_keywords',
            # Small computation outputs a screen reads right after its button: overrides shown at once, not next build.
            'pricing_claims', 'pricing_observations', 'pricing_days',
            # The operator's alert state, replaced whole from the MacBook at the cutover (a few hundred rows).
            'portfolio_principle_state', 'portfolio_alerts_sent', 'portfolio_event_estimates', 'alert_state', *NATIVE)
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


def projection_version(pg):
    changes = pg.execute('SELECT counter FROM legacy_projection_version WHERE singleton').fetchone()[0]
    generation = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0]
    return f'{generation}:{changes}'

def build_projection(factory, directory):
    path = Path(directory) / f'projection-{uuid.uuid4().hex}.db'
    root = sqlite3.connect(path)
    try:
        root.execute('PRAGMA journal_mode=OFF')
        root.execute('PRAGMA synchronous=OFF')
        with factory() as pg:
            pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(pg)
            version = projection_version(pg)
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
            for name in (*NATIVE, *NATIVE_FILE_ONLY):
                # Same column names as the legacy table; SQLite keeps each value's own type.
                columns = [row[0] for row in pg.execute('SELECT column_name FROM information_schema.columns WHERE '
                                                        'table_schema=current_schema() AND table_name=%s '
                                                        'ORDER BY ordinal_position', (name,))]
                quoted = ','.join('"' + column + '"' for column in columns)
                key = ','.join('"' + row[0] + '"' for row in pg.execute(
                    'SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) '
                    'WHERE i.indrelid=to_regclass(%s) AND i.indisprimary ORDER BY array_position(i.indkey,a.attnum)', (name,)))
                root.execute(f'CREATE TABLE "{name}" ({quoted}, PRIMARY KEY({key}))')
                rows = pg.execute(f'SELECT {quoted} FROM {name} WHERE {_operator_rows(pg, name)}').fetchall()
                root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})', rows)
            legacy_version = None
            if pg.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is not None:
                legacy_version, rows, _ = owner_legacy.load(pg)
                _derive_owner_legacy(root, pg, rows)
            _derive_owner_portfolio(root, pg)
            _derive_owner_records(root, pg)
            from pipeline import postgres_candidate_job_runs
            postgres_candidate_job_runs.derive(root, pg)
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


class LegacyProjection:
    def __init__(self, factory, directory, *, on_change=None, external=False):
        """`external`: a separate builder process (`postgres_legacy_projection_builder`) writes the files and
        a manifest; this process only switches to each new file, so the rebuild never uses its memory."""
        self.factory = factory
        self.on_change = on_change  # called after a rebuild caused by a ledger/overlay change
        self.directory = Path(directory)
        self.external = external
        if not external:
            self.directory.mkdir(parents=True, exist_ok=True)
            for stale in (*self.directory.glob('projection-*.db'), *self.directory.glob('current*')):
                stale.unlink()  # a previous process's files are never reused
        self.lock = threading.Lock()
        self.current = None  # (path, version)
        self.building = False
        self.polling = False
        self.failures = 0
        self.legacy_cache = None  # (version, rows, sequences) of the owner legacy ledger

    def _version(self, pg):
        return projection_version(pg)

    def _build(self):
        return build_projection(self.factory, self.directory)

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

    @property
    def manifest(self):
        return self.directory / 'current.json'

    def _read_manifest(self):
        try:
            data = json.loads(self.manifest.read_text())
        except FileNotFoundError:
            return None
        return self.directory / data['file'], data['version'], data['legacy_version']

    def _adopt_external(self):
        """Switch to the builder's latest file if it changed; run the change hook once per switch."""
        built = self._read_manifest()
        with self.lock:
            changed = built is not None and (self.current is None or built[:2] != self.current[:2])
            if changed:
                self.current = built
        if changed and self.on_change is not None:
            try:
                self.on_change()
            except Exception as exc:
                log.warning('Legacy projection change hook failed (%s)', type(exc).__name__)
        return changed

    def _check(self):
        if self.external:
            self._adopt_external()
            return
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
        if self.external:
            with self.lock:
                start, self.polling = not self.polling, True
            if start:
                threading.Thread(target=self._poll, daemon=True, name='legacy-projection-poll').start()
            for _ in range(600):  # the builder may still be writing the first file
                if self.current is not None or self._adopt_external():
                    return self.current[0]
                time.sleep(1)
            raise RuntimeError('No legacy projection from the builder')
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

    def _shadow(self, conn, *, writable=False, extra=(), scoped=False):
        """TEMP names shadow main ones; the unchanged derivations then write only the shadows."""
        with self.factory() as pg:
            pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            legacy = self._owner_legacy(pg)
            ddl = dict(pg.execute('SELECT table_name,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',
                                  (list(owner_legacy.TABLES),)).fetchall()) if writable else {}
            computed = ()
            if writable:  # decision tables keep their keys and checks, not their foreign keys
                from pipeline.postgres_owner_overrides import COMPUTED, OVERRIDES, writable_ddl
                ddl.update({name: writable_ddl(sql) for name, sql in pg.execute(
                    'SELECT table_name,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(OVERRIDES),))})
                computed = COMPUTED  # writable copies of computation outputs for this request only
                ddl.update({name: writable_ddl(sql) for name, sql in pg.execute(
                    'SELECT table_name,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(extra),))})
            # The file already holds this ledger version: skip re-deriving its large evaluation table.
            current = self.current
            fresh = not writable and legacy is not None and current is not None and current[2] == legacy[0]
            skip = {'watch_evaluations'} if fresh else set()
            for table in dict.fromkeys((*SHADOWED, *computed, *extra)):
                if table in skip:
                    continue
                if table in ddl:
                    # Original DDL keeps PKs, AUTOINCREMENT and cascades for the legacy writer.
                    conn.execute(re.sub(r'^\s*CREATE\s+TABLE\s+', 'CREATE TEMP TABLE ', ddl[table], flags=re.I))
                    if conn.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        conn.execute(f'INSERT INTO temp."{table}" SELECT * FROM main."{table}"')
                    # else: registered after this file was built; empty until the next build carries it
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
            # A read connection has no copies of computation outputs (its file already holds them).
            from pipeline.postgres_owner_overrides import COMPUTED
            _derive_owner_records(conn, pg, skip_overrides=() if writable else COMPUTED)
            _derive_native(conn, pg)
            from pipeline import postgres_client_errors
            postgres_client_errors.derive(conn, pg)  # small and frequent: never part of the file
            from pipeline import postgres_live_tables
            postgres_live_tables.derive(conn, pg)  # frequently collected small tables: from PG, not the file
            if (not writable or scoped) and not requester_is_operator():
                _scope_to_requester(conn, pg)  # `scoped`: a member's own groups, written by that member
            if writable and legacy:
                for table, seq in legacy[2].items():
                    # Never hand out an ID the legacy writer already used.
                    conn.execute('DELETE FROM temp.sqlite_sequence WHERE name=?', (table,))
                    conn.execute('INSERT INTO temp.sqlite_sequence(name,seq) VALUES (?,?)', (table, seq))
            if writable:
                # New legacy rows take the candidate's band, never the MacBook's next ids (pipeline.postgres_id_bands).
                from pipeline.postgres_id_bands import band
                if conn.execute("SELECT 1 FROM temp.sqlite_master WHERE name='sqlite_sequence'").fetchone():
                    band(conn, 'temp')
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
        conn.commit()  # the shadow inserts opened a transaction; legacy readers may BEGIN their own
        conn.execute('PRAGMA query_only=ON')
        return conn

    def write_connection(self, extra=(), *, scoped=False):
        """A projection connection whose owner tables are writable TEMP copies, with the ledger version.

        `extra` names more tables to copy writable for this request (a computation that writes the graph).
        `scoped`: a member's request sees (and writes) only that member's personal state, as its reads do.
        """
        conn = sqlite3.connect(f'file:{self.path()}?mode=ro', uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            version = self._shadow(conn, writable=True, extra=extra, scoped=scoped)
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


# Personal state a public reader other than the operator must not see (pipeline.postgres_principals):
# whole tables, rows of mixed tables, and the operator's personal flags on shared rows.
PERSONAL_TABLES = ('follows', 'kalshi_pins', 'channel_reads', 'saved_items', 'tracker_conditions', 'portfolio_transactions',
                   'portfolio_principles', 'stock_groups', 'stock_group_members', 'watch_rules', 'watch_evaluations',
                   'questions', 'sub_questions', 'study_projects',
                   # The operator's alert state (which principle rules are broken, which alerts were sent).
                   'portfolio_principle_state', 'portfolio_alerts_sent', 'portfolio_event_estimates', *NATIVE_FILE_ONLY)
PERSONAL_ROWS = (("DELETE FROM temp.knowledge WHERE model='user'"),  # knowledge the user injected
                 'DELETE FROM temp.proxy_observations WHERE proxy_id IN (SELECT id FROM temp.proxy_registry WHERE sub_question_id IS NOT NULL)',
                 'DELETE FROM temp.proxy_registry WHERE sub_question_id IS NOT NULL',  # proxies of the user's questions
                 'UPDATE temp.transcript_follow SET core_pinned=0',
                 # A source mute is the owner's personal setting; every collected source shows to others.
                 'UPDATE temp.telegram_channels SET is_active=1', 'UPDATE temp.youtube_channels SET is_active=1')


# A member's own rows of the per-account ledgers, shown in place of the operator's (see _scope_to_requester).
MEMBER_LEDGERS = {'saved_items': ('owner_saved_items', ('id', 'kind', 'ref', 'url', 'title', 'subtitle', 'note', 'created_at')),
                  'follows': ('owner_follows', ('id', 'entity_id', 'created_at')),
                  'kalshi_pins': ('owner_kalshi_pins', ('event_ticker', 'series_ticker', 'pinned_at')),
                  'channel_reads': ('owner_channel_reads', ('channel', 'read_until', 'updated_at')),
                  'tracker_conditions': ('owner_tracker_conditions', ('id', 'stock_code', 'role', 'kind', 'level', 'ma', 'label',
                                                                      'note', 'done', 'created_at', 'updated_at'))}


def requester_scope():
    """Whose personal state a read shows: the operator's, or a member's own ('principal', id; id None when anonymous)."""
    if requester_is_operator():
        return 'operator'
    from pipeline.postgres_principals import request_principal
    return 'principal', request_principal.get()


def requester_is_operator():
    """In the private (loopback) mode every reader is the operator. In the public mode only a request whose
    boundary-resolved principal is the operator reads the operator's personal state; anonymous visitors, other
    members and requests outside the boundary read none."""
    from security.access_boundary import configured_access_mode
    if configured_access_mode() != 'public':
        return True
    from pipeline.postgres_usage_gate import usage
    context = usage.get()
    return context is not None and context.role == 'operator'


def _scope_to_requester(conn, pg):
    """Empty the requester's view of the operator's personal state (TEMP shadows hide the file's tables,
    so whatever a legacy reader joins, it sees no one's records), then show a member's own (MEMBER_LEDGERS)."""
    temp = {row[0] for row in conn.execute("SELECT name FROM temp.sqlite_master WHERE type='table'")}
    if 'trade_follow' in temp:
        # The collected item catalog without the operator's on/off choices (owner_trade_follow).
        columns = [row[1] for row in conn.execute('PRAGMA temp.table_info("trade_follow")')]
        conn.execute('DELETE FROM temp.trade_follow')
        conn.executemany(f'INSERT INTO temp.trade_follow ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                         [tuple(row[0].get(c) for c in columns) for row in pg.execute(
                             "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='trade_follow' ORDER BY row_ordinal")])
    for table in PERSONAL_TABLES:
        if table in temp:
            conn.execute(f'DELETE FROM temp."{table}"')
        elif conn.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            conn.execute(f'CREATE TEMP TABLE "{table}" AS SELECT * FROM main."{table}" WHERE 0')
    _, principal = requester_scope()
    account = pg.execute('SELECT id FROM fixture_portfolio_accounts WHERE principal=%s', (principal,)).fetchone() if principal else None
    if account is not None:
        for table, (ledger, columns) in MEMBER_LEDGERS.items():
            if (conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                    and pg.execute('SELECT to_regclass(%s)', (ledger,)).fetchone()[0] is not None):
                conn.executemany(f'INSERT INTO temp."{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                                 pg.execute(f'SELECT {",".join(columns)} FROM {ledger} WHERE account_id=%s ORDER BY {columns[0]}',
                                            (account[0],)).fetchall())
    if account is not None:
        for table, rows in owner_legacy.member_rows(pg, account[0]).items():
            if rows and conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                columns = [row[1] for row in conn.execute(f'PRAGMA temp.table_info("{table}")')]
                quoted = ','.join('"' + column + '"' for column in columns)
                conn.executemany(f'INSERT INTO temp."{table}" ({quoted}) VALUES ({",".join("?" for _ in columns)})',
                                 (tuple(row.get(column) for column in columns) for row in rows))
    for statement in PERSONAL_ROWS:
        table = statement.split('temp.')[1].split()[0]
        if table not in temp:
            conn.execute(f'CREATE TEMP TABLE "{table}" AS SELECT * FROM main."{table}"')
            temp.add(table)
        conn.execute(statement)
    # A requester with no portfolio: the legacy readers create the default portfolio group on first read, which the
    # read-only file refuses (a 500). An empty group in this connection's copy lets them answer with nothing. The copy
    # (CREATE TABLE AS) has no column defaults, so the row gets the ones the legacy table would give it: without them
    # created_at was null and every anonymous page failed the groups contract (10,318 reports, 2026-11-17~22).
    if conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type='table' AND name='stock_groups'").fetchone() and \
            not conn.execute("SELECT 1 FROM temp.stock_groups WHERE kind='portfolio'").fetchone():
        from pipeline.portfolio import GROUP_NAME
        conn.execute("INSERT INTO temp.stock_groups (id, name, kind, note, created_at, updated_at) "
                     "VALUES (-1, ?, 'portfolio', '', datetime('now'), datetime('now'))", (GROUP_NAME,))


_MEMBER_QUESTION = "SELECT question_id FROM question_principals"
_MEMBER_ROWS = {  # a member's tracked questions stay out of the operator's legacy tables
    'questions': f'id NOT IN ({_MEMBER_QUESTION})',
    'sub_questions': f'question_id NOT IN ({_MEMBER_QUESTION})',
    'proxy_registry': f'sub_question_id IS NULL OR sub_question_id NOT IN (SELECT id FROM sub_questions WHERE question_id IN ({_MEMBER_QUESTION}))',
    'proxy_observations': ('proxy_id NOT IN (SELECT p.id FROM proxy_registry p JOIN sub_questions s ON s.id=p.sub_question_id '
                           f'WHERE s.question_id IN ({_MEMBER_QUESTION}))'),
}


_MEMBER_PROJECTS = 'SELECT project_id FROM study_project_principals'
_MEMBER_STUDIES = ('SELECT id FROM study_sessions WHERE id IN (SELECT study_id FROM study_principals) '
                   f'OR project_id IN ({_MEMBER_PROJECTS})')
_MEMBER_STUDY_ROWS = {  # members' studies (pipeline.postgres_study_owners) likewise
    'study_projects': f'id NOT IN ({_MEMBER_PROJECTS})',
    'study_sessions': f'id NOT IN ({_MEMBER_STUDIES})',
    'study_project_members': f'project_id NOT IN ({_MEMBER_PROJECTS})',
    'study_annotations': f'study_id NOT IN ({_MEMBER_STUDIES})',
}


def _operator_rows(pg, name):
    """The rows of a PG-native ledger the projection (the operator's legacy view) shows."""
    for rows, mapping in ((_MEMBER_ROWS, 'question_principals'), (_MEMBER_STUDY_ROWS, 'study_principals')):
        if name in rows and pg.execute('SELECT to_regclass(%s)', (mapping,)).fetchone()[0] is not None:
            return rows[name]
    return 'true'


def _derive_native(root, pg):
    """Current rows of the PG-native ledgers (questions, study projects), so new ones show at once."""
    for name in NATIVE:
        columns = [row[1] for row in root.execute(f'PRAGMA table_info("{name}")')]
        quoted = ','.join('"' + column + '"' for column in columns)
        root.execute(f'DELETE FROM "{name}"')
        root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" for _ in columns)})',
                         pg.execute(f'SELECT {quoted} FROM {name} WHERE {_operator_rows(pg, name)}').fetchall())


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


def _derive_owner_records(root, pg, *, skip_overrides=()):
    """Show the mapped owner's follows and prediction pins through the legacy tables (never a member's rows)."""
    if pg.execute("SELECT to_regclass('owner_follows')").fetchone()[0] is None:
        return
    root.execute('DELETE FROM follows')
    root.executemany('INSERT INTO follows (id,entity_id,created_at) VALUES (?,?,?)',
                     pg.execute('SELECT id,entity_id,created_at FROM owner_follows WHERE account_id=(SELECT account_id FROM fixture_portfolio_legacy_mapping) ORDER BY id').fetchall())
    root.execute('DELETE FROM kalshi_pins')
    root.executemany('INSERT INTO kalshi_pins (event_ticker,series_ticker,pinned_at) VALUES (?,?,?)',
                     pg.execute('SELECT event_ticker,series_ticker,pinned_at FROM owner_kalshi_pins WHERE account_id=(SELECT account_id FROM fixture_portfolio_legacy_mapping)').fetchall())
    if pg.execute("SELECT to_regclass('owner_channel_reads')").fetchone()[0] is not None:
        root.execute('DELETE FROM channel_reads')
        root.executemany('INSERT INTO channel_reads (channel,read_until,updated_at) VALUES (?,?,?)',
                         pg.execute('SELECT channel,read_until,updated_at FROM owner_channel_reads WHERE account_id=(SELECT account_id FROM fixture_portfolio_legacy_mapping)').fetchall())
    if pg.execute("SELECT to_regclass('owner_saved_items')").fetchone()[0] is not None:
        root.execute('DELETE FROM saved_items')
        root.executemany('INSERT INTO saved_items (id,kind,ref,url,title,subtitle,note,created_at) VALUES (?,?,?,?,?,?,?,?)',
                         pg.execute('SELECT id,kind,ref,url,title,subtitle,note,created_at FROM owner_saved_items WHERE account_id=(SELECT account_id FROM fixture_portfolio_legacy_mapping) ORDER BY id').fetchall())
    if pg.execute("SELECT to_regclass('owner_tracker_conditions')").fetchone()[0] is not None:
        root.execute('DELETE FROM tracker_conditions')
        root.executemany('INSERT INTO tracker_conditions (id,stock_code,role,kind,level,ma,label,note,done,created_at,updated_at) '
                         'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         pg.execute('SELECT id,stock_code,role,kind,level,ma,label,note,done,created_at,updated_at '
                                    'FROM owner_tracker_conditions WHERE account_id=(SELECT account_id FROM fixture_portfolio_legacy_mapping) ORDER BY id').fetchall())
    derive_owner_transcript_follow(root, pg)
    if pg.execute("SELECT to_regclass('owner_knowledge_reviews')").fetchone()[0] is not None:
        # Operator decisions win over whatever the collector judged for the same knowledge.
        root.executemany('UPDATE knowledge SET review_status=?,epistemic_status=COALESCE(?,epistemic_status) WHERE id=?',
                         pg.execute('SELECT review_status,epistemic_status,knowledge_id FROM owner_knowledge_reviews').fetchall())
    if pg.execute("SELECT to_regclass('owner_source_additions')").fetchone()[0] is not None:
        # Sources the operator added that the collected rows do not have yet.
        from pipeline.postgres_owner_records_fixture import SOURCE_TABLES
        for kind, key, data in pg.execute('SELECT kind,key,row_data FROM owner_source_additions ORDER BY added_at,key'):
            table, column = SOURCE_TABLES[kind]
            if root.execute(f'SELECT 1 FROM {table} WHERE {column}=?', (key,)).fetchone():
                continue
            columns = [row[1] for row in root.execute(f'PRAGMA table_info({table})') if row[1] in data]
            root.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                         [data[column] for column in columns])
    if pg.execute("SELECT to_regclass('owner_source_settings')").fetchone()[0] is not None:
        # The operator's mute/collection switches over the collected source rows.
        from pipeline.postgres_owner_records_fixture import SOURCE_TABLES
        for kind, key, active, collect in pg.execute('SELECT kind,key,is_active,collect_enabled FROM owner_source_settings'):
            table, column = SOURCE_TABLES[kind]
            root.execute(f'UPDATE {table} SET is_active=COALESCE(?,is_active),collect_enabled=COALESCE(?,collect_enabled) '
                         f'WHERE {column}=?', (active, collect, key))
    derive_owner_narrative_decisions(root, pg)
    from pipeline.postgres_owner_overrides import derive as derive_overrides
    derive_overrides(root, pg, skip=skip_overrides)
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


def derive_owner_narrative_decisions(root, pg):
    """Admin decisions over the collected narrative candidates."""
    if pg.execute("SELECT to_regclass('owner_narrative_decisions')").fetchone()[0] is None:
        return
    # Admin decisions over the collected candidates; a dismissal lapses after its date (legacy: 14 days).
    from pipeline.market_today_links import _today_kst
    today = _today_kst().isoformat()
    for tag, status, topic, mode, aliases, until in pg.execute(
            'SELECT tag,status,narrative_topic,mode,alias_tags,dismissed_until FROM owner_narrative_decisions'):
        if status == 'dismissed' and (until or '') < today:
            continue
        patch = {key: value for key, value in (('mode', mode), ('alias_tags', aliases)) if value is not None}
        root.execute("UPDATE narrative_candidates SET status=?,narrative_topic=?,dismissed_until=?,"
                     "detail_json=json_patch(COALESCE(detail_json,'{}'),?) WHERE tag=?",
                     (status, topic, until, json.dumps(patch, ensure_ascii=False), tag))


# Operator decisions laid over collected rows that every reader shares on purpose (not personal state).
SHARED_DECISIONS = ('feature_flags', 'era_checks', 'research_candidates', 'agent_proposals', 'entity_keywords',
                    'pricing_claims', 'pricing_observations', 'pricing_days')


def check_override_shadows(pg):
    """Public-mode self-check (architect #3 6947039949): every override table a read connection lays over the file must
    have a TEMP shadow there (else the derive writes the read-only file and every read fails), and a personal one
    must be in the operator's personal state (else a member reads it). Returns the warnings; raises on the first kind."""
    from pipeline.postgres_owner_overrides import COMPUTED, OVERRIDES
    registered = {name for (name,) in pg.execute('SELECT table_name FROM owner_override_keys')} \
        if pg.execute("SELECT to_regclass('owner_override_keys')").fetchone()[0] is not None else set()
    laid = (set(OVERRIDES) | registered) - set(COMPUTED)
    # A withdrawn close-alert adapter may have registered keys before it wrote any rows.
    # Leave that PG metadata intact, and waive only those unused, inactive keys.
    withdrawn_close = {'catalysts', 'portfolio_event_estimates', 'transcript_calendar', 'entity_digests'}
    candidates = (registered & withdrawn_close) - set(OVERRIDES)
    active = {name for (name,) in pg.execute(
        'SELECT DISTINCT table_name FROM owner_row_overrides WHERE table_name=ANY(%s)', (sorted(candidates),))} if candidates else set()
    unshadowed = sorted(laid - set(SHADOWED) - (candidates - active))
    if unshadowed:
        raise RuntimeError(f'Override tables without a read shadow (every read would fail): {unshadowed}')
    by_row = {statement.split('temp.')[1].split()[0] for statement in PERSONAL_ROWS}  # personal rows of shared tables
    return [f'override table {name} is neither shared on purpose nor personal' for name in
            sorted(laid - set(SHARED_DECISIONS) - set(PERSONAL_TABLES) - by_row)]

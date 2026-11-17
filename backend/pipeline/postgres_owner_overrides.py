"""Operator decisions and on-demand computations over collected rows, by key (single-path candidate).

Admin flags, regime checklist entries, research-candidate and agent-proposal dismissals, and alias
rejections change a few rows of tables the collector also writes; screen computations (investor
lens, source profile, upside model, MER narrative) write one result row each. The unchanged legacy handler runs
on writable TEMP copies of these tables (`routers.postgres_owner_overrides_fixture`); the rows it
changed are kept here and laid over the collected rows in every read path (`legacy_snapshot_rows`
itself, after `install_view`) and in the collector export. A removed row is kept as a NULL override.
"""
import logging
import re

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

log = logging.getLogger(__name__)

# table -> natural key column
OVERRIDES = {'feature_flags': 'name', 'era_checks': 'key', 'research_candidates': 'id',
             'agent_proposals': 'id', 'entity_keywords': 'id',
             'lens_readings': 'id', 'source_digests': 'id', 'models': 'id', 'narratives': 'id',
             'knowledge_falsifiers': 'id', 'knowledge': 'id', 'knowledge_evidence': 'id',
             # A composite key is 'a|b' (the column values joined by '|'), for the PG view as for the build.
             'knowledge_entities': 'knowledge_id|entity_id',
             'earnings_expectations': 'ticker|fiscal_year|fiscal_period|snapshot',
             'scenarios': 'topic', 'reports': 'id', 'company_profiles': 'id', 'trade_beneficiaries': 'id',
             'stock_briefs': 'id', 'era_commentary': 'input_hash', 'thesis_audits': 'id',
             'transcript_reactions': 'transcript_id', 'transcripts': 'id', 'knowledge_doc_scans': 'doc_id',
             'signals': 'id',  # computed by the chain's signal step (upsert per type, entity, date)
             'pipeline_runs': 'name',  # batch markers computations leave (knowledge promotion and others)
             'pricing_claims': 'id', 'pricing_observations': 'trade_date|claim_id', 'pricing_days': 'trade_date'}
# Computation outputs: copied into TEMP only for the computing request; reads see them from the
# next projection build (the computing request answers with the result itself).
COMPUTED = ('lens_readings', 'source_digests', 'models', 'narratives', 'knowledge_falsifiers',
            'knowledge_evidence', 'knowledge_entities', 'scenarios', 'reports', 'company_profiles', 'trade_beneficiaries',
            'stock_briefs', 'era_commentary', 'thesis_audits',
            'transcript_reactions', 'transcripts', 'earnings_expectations', 'knowledge_doc_scans', 'signals', 'pipeline_runs')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('owner_row_overrides')").fetchone()[0] is not None:
            raise ValueError('Row overrides already initialized')
        conn.execute('CREATE TABLE owner_row_overrides (table_name TEXT NOT NULL,key TEXT NOT NULL,row_data JSONB,'
                     'updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(table_name,key))')


def install_view(conn):
    """Show the kept rows through `legacy_snapshot_rows` itself, so PG-native readers see them too.

    An override replaces the row with the same key at the same ordinal; a new key gets its own
    ordinal after the table's rows; a NULL override hides the row.
    """
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('owner_override_keys')").fetchone()[0] is not None:
            raise ValueError('Override view already installed')
        conn.execute('ALTER TABLE owner_row_overrides ADD COLUMN row_ordinal BIGINT')
        conn.execute('CREATE TABLE owner_override_keys (table_name TEXT PRIMARY KEY,key_column TEXT NOT NULL)')
        conn.cursor().executemany('INSERT INTO owner_override_keys VALUES (%s,%s)', list(OVERRIDES.items()))
        definition = conn.execute("SELECT pg_get_viewdef(to_regclass('legacy_snapshot_rows'),true)").fetchone()[0]
        conn.execute(f'''CREATE OR REPLACE VIEW legacy_snapshot_rows AS
            SELECT v.table_name,v.row_ordinal,v.row_data FROM ({definition.rstrip().rstrip(";")}) v
            WHERE NOT EXISTS (SELECT 1 FROM owner_row_overrides o JOIN owner_override_keys k USING (table_name)
                              WHERE o.table_name=v.table_name AND o.key=v.row_data->>k.key_column){COMPOSITE_HIDE}
            UNION ALL SELECT table_name,row_ordinal,row_data FROM owner_row_overrides WHERE row_data IS NOT NULL''')


# Rows of composite-key tables (key 'a|b': the column values joined by '|', as `_key`) are matched in a second
# test that only those tables' rows reach, so the single-column lookup stays as cheap as before.
COMPOSITE_HIDE = (" AND (v.table_name NOT IN (SELECT table_name FROM owner_override_keys WHERE strpos(key_column,'|')>0)"
                  " OR NOT EXISTS (SELECT 1 FROM owner_row_overrides o2 JOIN owner_override_keys k2 USING (table_name)"
                  " WHERE o2.table_name=v.table_name AND o2.key=(SELECT string_agg(v.row_data->>u.c,'|' ORDER BY u.n)"
                  " FROM unnest(string_to_array(k2.key_column,'|')) WITH ORDINALITY u(c,n))))")
OWNER_ROWS = '\nUNION ALL\n SELECT owner_row_overrides.table_name,'


def support_composite_keys(conn):
    """Let an installed view hide rows by composite keys too (installed before composite keys could hide)."""
    import re
    _guard(conn)
    with conn.transaction():
        definition = conn.execute("SELECT pg_get_viewdef(to_regclass('legacy_snapshot_rows'),true)").fetchone()[0]
        # An earlier form put the composite key into the single-column test (slow over every row): undo it.
        definition = re.sub(r'o\.key =\s*CASE\s.*?\bEND\)\)', 'o.key = (v.row_data ->> k.key_column)))', definition, flags=re.S)
        if 'o2.key' in definition or definition.count(OWNER_ROWS) != 1:
            raise ValueError('Unexpected override view definition')
        conn.execute('CREATE OR REPLACE VIEW legacy_snapshot_rows AS ' + definition.rstrip().rstrip(';').replace(
            OWNER_ROWS, COMPOSITE_HIDE + OWNER_ROWS))


def writable_ddl(ddl):
    """The table's own DDL without foreign keys: its parents are not copied into TEMP."""
    return re.sub(r'\s+REFERENCES\s+\w+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*',
                  '', ddl, flags=re.I)


def _columns(table):
    return OVERRIDES[table].split('|')


def _key(table, row):
    return '|'.join(str(row[column]) for column in _columns(table))


def rows(conn):
    """{table: {key: row}} of a SQLite connection's (TEMP) override tables."""
    out = {}
    temp = {row[0] for row in conn.execute("SELECT name FROM temp.sqlite_master WHERE type='table'")}
    for table, key in OVERRIDES.items():
        if table in temp:
            out[table] = {_key(table, row): dict(row) for row in conn.execute(f'SELECT * FROM temp."{table}"')}
    return out


def record_outputs(conn, source, rows):
    """Note rows the candidate itself produced, so the final sync can clean up or re-map them
    (the MacBook keeps issuing IDs in the same space)."""
    if conn.execute("SELECT to_regclass('candidate_outputs')").fetchone()[0] is None:
        conn.execute("CREATE TABLE candidate_outputs (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,source TEXT NOT NULL,"
                     "table_name TEXT NOT NULL,row_key TEXT NOT NULL,origin TEXT NOT NULL DEFAULT 'candidate',"
                     'created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
    for table, key in rows:
        conn.execute('INSERT INTO candidate_outputs(source,table_name,row_key) VALUES (%s,%s,%s)', (source, table, str(key)))


def apply(conn, before, after, *, source=None):
    """Store what one successful request changed; returns the number of changed rows."""
    changed = 0
    touched = []
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-row-overrides',0))")
    if conn.execute("SELECT to_regclass('owner_override_keys')").fetchone()[0] is not None:
        conn.cursor().executemany('INSERT INTO owner_override_keys VALUES (%s,%s) ON CONFLICT (table_name) DO NOTHING',
                                  list(OVERRIDES.items()))
    for table in after:
        old, new = before[table], after[table]
        for key in set(old) | set(new):
            if old.get(key) != new.get(key):
                row = new.get(key)
                # Keep the visible row's place; a new row goes after the table's rows.
                match = ' AND '.join(f"row_data->>'{column}'=%s" for column in _columns(table))
                ordinal = conn.execute(f'SELECT row_ordinal FROM legacy_snapshot_rows WHERE table_name=%s AND {match}',
                                       (table, *key.split('|'))).fetchone()
                if ordinal is None:
                    ordinal = conn.execute('SELECT COALESCE(max(row_ordinal),0)+1 FROM legacy_snapshot_rows WHERE table_name=%s',
                                           (table,)).fetchone()
                conn.execute('INSERT INTO owner_row_overrides(table_name,key,row_data,row_ordinal) VALUES (%s,%s,%s,%s) '
                             'ON CONFLICT (table_name,key) DO UPDATE SET row_data=excluded.row_data,updated_at=now()',
                             (table, key, Jsonb(row) if row is not None else None, ordinal[0]))
                changed += 1
                touched.append((table, key))
    if source and touched:
        record_outputs(conn, source, touched)
    return changed


def derive(root, pg, *, skip=()):
    """Lay the kept decisions over the collected rows (a NULL override removes the row)."""
    if pg.execute("SELECT to_regclass('owner_row_overrides')").fetchone()[0] is None:
        return
    # Removals first: one request may hide rows and add rows under the same unique columns (an idempotent
    # replace), and its overrides share one timestamp.
    for table, key, row in pg.execute('SELECT table_name,key,row_data FROM owner_row_overrides '
                                      'ORDER BY row_data IS NOT NULL,updated_at,table_name,key'):
        if table in skip:
            continue
        if table not in OVERRIDES:  # written by newer code than this process runs; never break every read for it
            log.warning('Skipping override for unknown table %s (restart to load it)', table)
            continue
        match = ' AND '.join(f'"{column}"=?' for column in _columns(table))
        values = key.split('|')
        if row is None:
            root.execute(f'DELETE FROM "{table}" WHERE {match}', values)
            continue
        columns = [c[1] for c in root.execute(f'PRAGMA table_info("{table}")') if c[1] in row]
        if root.execute(f'UPDATE "{table}" SET {",".join(f"{c}=?" for c in columns)} WHERE {match}',
                        [row[c] for c in columns] + values).rowcount == 0:
            root.execute(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                         [row[c] for c in columns])

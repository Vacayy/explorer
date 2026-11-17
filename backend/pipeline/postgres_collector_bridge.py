"""Interim collector bridge for the single-path preview (compatibility path, not the target design).

Unchanged legacy collectors keep writing their own SQLite file (single writer).
Before a run, the owner's PG ledgers are exported into that file's legacy tables
so collectors read current pins, groups and rules; after a run, the collected
tables are copied back into the candidate's supplement layer in one transaction.
Base snapshot tables are never replaced here.
"""
import json
import sqlite3

from pipeline.postgres_graph_fixture import _guard


def export_owner_records(pg, collector):
    """Write the owner's current ledgers into the collector's legacy tables."""
    from pipeline import postgres_owner_legacy_fixture as owner_legacy
    from pipeline.postgres_legacy_projection import _derive_owner_legacy, _derive_owner_portfolio, _derive_owner_records
    _guard(pg)
    if pg.execute("SELECT to_regclass('owner_legacy_rows')").fetchone()[0] is not None:
        _derive_owner_legacy(collector, pg, owner_legacy.load(pg)[1])
    _derive_owner_portfolio(collector, pg)
    _derive_owner_records(collector, pg)
    collector.commit()


def refresh_supplement(pg, collector_path, tables):
    """Replace the named supplement tables with the collector's rows, atomically."""
    _guard(pg)
    source = sqlite3.connect(f'file:{collector_path}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute('BEGIN')  # one consistent read of the collector file
        counts = {}
        with pg.transaction():
            pg.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')
            known = {name: columns for name, columns in pg.execute(
                'SELECT table_name,columns FROM legacy_supplement_tables WHERE table_name=ANY(%s)', (list(tables),))}
            if set(known) != set(tables):
                raise ValueError('Only existing supplement tables can be refreshed')
            from pipeline import postgres_live_tables
            live = postgres_live_tables.ready(pg)
            for name in tables:
                if live:
                    postgres_live_tables.mark(pg, name)  # which counter this table's statements bump
                columns = [row['name'] for row in source.execute(f'PRAGMA table_info("{name}")')]
                if columns != known[name]:
                    raise ValueError(f'Collector schema differs: {name}')
                pg.execute('DELETE FROM legacy_supplement_rows WHERE table_name=%s', (name,))
                count = 0
                with pg.cursor().copy('COPY legacy_supplement_rows (table_name,row_ordinal,row_data) FROM STDIN') as copy:
                    for ordinal, row in enumerate(source.execute(f'SELECT * FROM "{name}"')):
                        copy.write_row((name, ordinal, json.dumps(dict(row), ensure_ascii=False, allow_nan=False)))
                        count = ordinal + 1
                pg.execute('UPDATE legacy_supplement_tables SET row_count=%s WHERE table_name=%s', (count, name))
                counts[name] = count
        return counts
    finally:
        source.close()


def apply_entity_merges(pg, collector_path):
    """Point PG ledgers at the survivor of entity merges the collector made; returns what was applied.

    The legacy merge rewires every FK inside the collector file only, and its log
    keeps the loser's name, not its id: the loser is the visible entity of that
    type and name. Duplicates collapse onto the survivor's row (a follow keeps
    the earlier time). A merge whose survivor PG does not show yet waits.
    """
    _guard(pg)
    source = sqlite3.connect(f'file:{collector_path}?mode=ro', uri=True)
    try:
        merges = source.execute('SELECT id,old_name,type,survivor_id FROM entity_merges ORDER BY id').fetchall()
    finally:
        source.close()
    applied, waiting = [], []
    with pg.transaction():
        pg.execute('CREATE TABLE IF NOT EXISTS owner_entity_merges_applied (merge_id BIGINT PRIMARY KEY,loser_id BIGINT,'
                   "survivor_id BIGINT NOT NULL,applied_at TEXT NOT NULL DEFAULT to_char(clock_timestamp() AT TIME ZONE 'UTC',"
                   "'YYYY-MM-DD HH24:MI:SS'))")
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended('owner-entity-merges',0))")
        done = {row[0] for row in pg.execute('SELECT merge_id FROM owner_entity_merges_applied')}
        for merge_id, name, kind, survivor in merges:
            if merge_id in done:
                continue
            if not pg.execute("SELECT 1 FROM legacy_snapshot_rows WHERE table_name='entities' AND row_data->>'id'=%s",
                              (str(survivor),)).fetchone():
                waiting.append(merge_id)
                continue
            losers = [row[0] for row in pg.execute(
                "SELECT (row_data->>'id')::bigint FROM legacy_snapshot_rows WHERE table_name='entities' "
                "AND row_data->>'type'=%s AND row_data->>'name'=%s AND row_data->>'id'<>%s", (kind, name, str(survivor)))]
            if len(losers) > 1:
                raise ValueError(f'Ambiguous merged entity: {kind}/{name}')
            loser = losers[0] if losers else None
            if loser is not None:
                pg.execute('UPDATE owner_follows s SET created_at=LEAST(s.created_at,l.created_at) FROM owner_follows l '
                           'WHERE s.account_id=l.account_id AND s.entity_id=%s AND l.entity_id=%s', (survivor, loser))
                pg.execute('DELETE FROM owner_follows l WHERE l.entity_id=%s AND EXISTS (SELECT 1 FROM owner_follows s '
                           'WHERE s.account_id=l.account_id AND s.entity_id=%s)', (loser, survivor))
                pg.execute('UPDATE owner_follows SET entity_id=%s WHERE entity_id=%s', (survivor, loser))
                pg.execute('DELETE FROM chat_entity_links l WHERE l.entity_id=%s AND EXISTS (SELECT 1 FROM chat_entity_links s '
                           'WHERE s.message_id=l.message_id AND s.entity_id=%s)', (loser, survivor))
                pg.execute('UPDATE chat_entity_links SET entity_id=%s WHERE entity_id=%s', (survivor, loser))
                pg.execute('DELETE FROM observations l WHERE l.entity_id=%s AND EXISTS (SELECT 1 FROM observations s '
                           'WHERE s.entity_id=%s AND s.date=l.date AND s.metric=l.metric AND s.source=l.source)', (loser, survivor))
                pg.execute('UPDATE observations SET entity_id=%s WHERE entity_id=%s', (survivor, loser))
                pg.execute('UPDATE conversations SET anchor_entity_id=%s WHERE anchor_entity_id=%s', (survivor, loser))
            pg.execute('INSERT INTO owner_entity_merges_applied(merge_id,loser_id,survivor_id) VALUES (%s,%s,%s)',
                       (merge_id, loser, survivor))
            applied.append((merge_id, loser, survivor))
    return {'applied': applied, 'waiting': waiting}


def relink_market_today(pg, projection_path, mt_ids):
    """Re-run the legacy Market Today narrative linker for some sessions and store the result in PG.

    What `market_today_links.approve` does at once for a merge approval: the unchanged linker runs on a
    private SQLite that reads the projection (attached read-only) and holds writable copies of the two
    tables it writes plus the candidates with the admin decisions applied; only its result for these
    sessions replaces the collected rows. The collector computes the same at its next run.
    """
    from pipeline.market_today_links import link_narratives
    from pipeline.postgres_legacy_projection import derive_owner_narrative_decisions
    _guard(pg)
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        db.execute('ATTACH DATABASE ? AS src', (f'file:{projection_path}?mode=ro',))
        marks = ','.join('?' * len(mt_ids))
        for table, where in (('market_today', f'id IN ({marks})'), ('market_today_links', f'mt_id IN ({marks})'),
                             ('narrative_candidates', '1=1')):
            ddl = db.execute('SELECT sql FROM src.sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone()[0]
            db.execute(ddl)  # main.<table> shadows src.<table> for the linker's unqualified names
            db.execute(f'INSERT INTO main.{table} SELECT * FROM src.{table} WHERE {where}', mt_ids if where != '1=1' else ())
        derive_owner_narrative_decisions(db, pg)
        for mt_id in mt_ids:
            link_narratives(db, mt_id)
        links = [dict(row) for row in db.execute(f'SELECT * FROM main.market_today_links WHERE mt_id IN ({marks}) ORDER BY rowid', mt_ids)]
        sessions = {row['id']: dict(row) for row in db.execute(f'SELECT * FROM main.market_today WHERE id IN ({marks})', mt_ids)}
    finally:
        db.close()
    with pg.transaction():
        pg.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')  # not during a collected-table refresh
        pg.execute("DELETE FROM legacy_supplement_rows WHERE table_name='market_today_links' AND (row_data->>'mt_id')::bigint=ANY(%s)",
                   (list(mt_ids),))
        start = pg.execute("SELECT COALESCE(max(row_ordinal),-1)+1 FROM legacy_supplement_rows WHERE table_name='market_today_links'").fetchone()[0]
        for position, row in enumerate(links):
            pg.execute("INSERT INTO legacy_supplement_rows VALUES ('market_today_links',%s,%s)",
                       (start + position, json.dumps(row, ensure_ascii=False)))
        for mt_id, row in sessions.items():
            pg.execute("UPDATE legacy_supplement_rows SET row_data=%s WHERE table_name='market_today' AND (row_data->>'id')::bigint=%s",
                       (json.dumps(row, ensure_ascii=False), mt_id))
        for table in ('market_today_links', 'market_today'):
            pg.execute('UPDATE legacy_supplement_tables SET row_count=(SELECT count(*) FROM legacy_supplement_rows WHERE table_name=%s) '
                       'WHERE table_name=%s', (table, table))
    return len(links)

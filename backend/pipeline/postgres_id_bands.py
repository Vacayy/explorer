"""The candidate's own legacy id band (architect #3 6943703383, 6945367459).

Every new legacy row the candidate makes — a collection job's work copy, a computation's or a ledger edit's writable
TEMP copies — takes its AUTOINCREMENT id from the band up, so the MacBook's ids (below it) and the candidate's never
meet at the cutover. All AUTOINCREMENT tables, not a hand list; evidence ids already pass 100 million on the MacBook
(replaced rows advance them), so their band starts higher. Idempotent: an id already at or above its band stays.
"""
BAND = 100_000_000
HIGHER = {'narrative_edge_evidence': 10_000_000_000}


def start(table):
    return HIGHER.get(table, BAND)


def band(conn, schema='main'):
    """Move each AUTOINCREMENT table's next id in `schema` ('main' or 'temp') into the band; returns the tables moved."""
    moved = []
    tables = conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND upper(sql) LIKE '%AUTOINCREMENT%'").fetchall()
    for (table,) in tables:
        first = start(table)
        current = max(conn.execute(f'SELECT COALESCE(max(rowid),0) FROM {schema}."{table}"').fetchone()[0],
                      (conn.execute(f'SELECT seq FROM {schema}.sqlite_sequence WHERE name=?', (table,)).fetchone() or (0,))[0])
        if current < first - 1:
            conn.execute(f'DELETE FROM {schema}.sqlite_sequence WHERE name=?', (table,))
            conn.execute(f'INSERT INTO {schema}.sqlite_sequence (name, seq) VALUES (?,?)', (table, first - 1))
            moved.append(table)
    return moved

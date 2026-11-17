"""Compare-and-apply one scrap ledger row inside a feed publication transaction."""
from psycopg.types.json import Jsonb
from psycopg.pq import TransactionStatus


def apply(pg, *, before, after):
    """Preserve unrelated rows; refuse concurrent edits instead of replacing a whole table.

    The caller must hold its outer publication transaction, including the document
    and receipt. Both row versions come from private collector state, never logs.
    """
    if pg.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError('Scrap ledger update requires an active outer transaction')
    if not after or not after.get('url') or (before is not None and before.get('url') != after['url']):
        raise ValueError('A stable scrap ledger key is required')
    pg.execute('LOCK TABLE legacy_supplement_tables IN EXCLUSIVE MODE')
    spec = pg.execute("SELECT columns FROM legacy_supplement_tables WHERE table_name='scrap_links'").fetchone()
    if spec is None or set(spec[0]) != set(after) or (before is not None and set(before) != set(after)):
        raise ValueError('Scrap ledger schema differs')
    rows = pg.execute("SELECT row_ordinal,row_data FROM legacy_supplement_rows WHERE table_name='scrap_links' "
                      "AND row_data->>'url'=%s", (after['url'],)).fetchall()
    if len(rows) > 1 or (rows[0][1] if rows else None) != before:
        raise RuntimeError('Scrap ledger changed since the collector snapshot')
    from pipeline import postgres_live_tables
    if postgres_live_tables.ready(pg):
        postgres_live_tables.mark(pg, 'scrap_links')
    if rows:
        pg.execute("UPDATE legacy_supplement_rows SET row_data=%s WHERE table_name='scrap_links' AND row_ordinal=%s",
                   (Jsonb(after), rows[0][0]))
    else:
        ordinal = pg.execute("SELECT COALESCE(max(row_ordinal),-1)+1 FROM legacy_supplement_rows "
                             "WHERE table_name='scrap_links'").fetchone()[0]
        pg.execute("INSERT INTO legacy_supplement_rows(table_name,row_ordinal,row_data) VALUES ('scrap_links',%s,%s)",
                   (ordinal, Jsonb(after)))
        pg.execute("UPDATE legacy_supplement_tables SET row_count=row_count+1 WHERE table_name='scrap_links'")

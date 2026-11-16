"""Disposable, same-backup portfolio read trial; never a production importer."""
import json
from datetime import date, timedelta

from psycopg.types.json import Jsonb

from pipeline.postgres_portfolio_archive_import import PortfolioArchiveConflict, import_principle_archive
from pipeline.postgres_graph_fixture import _guard


READ_TABLES = ('stock_groups', 'portfolio_transactions', 'portfolio_quotes', 'companies', 'stock_prices')


def import_read_snapshot(source, target):
    """Stage owner ledger and only its price history from one consistent backup."""
    _guard(target)
    source.execute('PRAGMA query_only=ON')
    if not source.in_transaction:
        source.execute('BEGIN')
    transactions = source.execute('SELECT stock_code,trade_date FROM portfolio_transactions ORDER BY trade_date,id').fetchall()
    codes = sorted({r[0] for r in transactions if r[0]})
    first_day = transactions[0][1] if transactions else None
    with target.transaction():
        target.execute('LOCK TABLE legacy_snapshot_tables,legacy_snapshot_rows IN EXCLUSIVE MODE')
        if target.execute('SELECT EXISTS(SELECT 1 FROM legacy_snapshot_tables WHERE table_name=ANY(%s))',
                          (list(READ_TABLES),)).fetchone()[0]:
            raise PortfolioArchiveConflict('target already contains portfolio read data')
        counts = import_principle_archive(source, target)
        for table in READ_TABLES:
            meta = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not meta or not meta[0]:
                raise PortfolioArchiveConflict(f'source table missing: {table}')
            columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            if table in ('companies', 'stock_prices'):
                if codes:
                    query = f'SELECT * FROM "{table}" WHERE stock_code IN ({",".join("?" for _ in codes)})'
                    params = list(codes)
                    if table == 'stock_prices':
                        query += " AND trade_date >= date(?, '-14 day')"
                        params.append(first_day)
                    cursor = source.execute(query + ' ORDER BY rowid', params)
                else:
                    cursor = []
            else:
                cursor = source.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            rows = [dict(zip(columns, row)) for row in cursor]
            target.execute('INSERT INTO legacy_snapshot_tables VALUES (%s,%s,%s,%s)',
                           (table, Jsonb(columns), meta[0], len(rows)))
            with target.cursor() as out:
                out.executemany('INSERT INTO legacy_snapshot_rows VALUES (%s,%s,%s)',
                                [(table, i, Jsonb(row)) for i, row in enumerate(rows)])
            counts[table] = len(rows)
    return counts


def read_portfolio_tool(connect):
    """Use original single-owner calculations without a disk SQLite fallback."""
    import sqlite3
    from pipeline import portfolio_principles as pp
    from pipeline.chat_tools import get_portfolio
    from pipeline.postgres_urgent_selection_fixture import open_snapshot
    with connect() as pg:
        pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        present = {r[0] for r in pg.execute(
            'SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(READ_TABLES),))}
        normalized_prices = 'stock_prices' not in present
        tables = tuple(t for t in READ_TABLES if t != 'stock_prices' or not normalized_prices) + ('portfolio_principles',)
        db, uri, _ = open_snapshot(pg, tables)
        try:
            if normalized_prices:
                metadata = pg.execute('SELECT m.generation_id,m.linked_document_generation,s.generation_id '
                                      'FROM sector_market_metadata m CROSS JOIN snapshot_metadata s '
                                      'WHERE m.singleton AND s.singleton').fetchone()
                if not metadata or not metadata[1] or metadata[0] != metadata[2]:
                    raise PortfolioArchiveConflict('market and document generations differ')
                txs = db.execute('SELECT stock_code,trade_date FROM portfolio_transactions ORDER BY trade_date,id').fetchall()
                codes = sorted({r['stock_code'] for r in txs if r['stock_code']})
                since = (date.fromisoformat(txs[0]['trade_date']) - timedelta(days=14)).isoformat() if txs else None
                db.execute('CREATE TABLE stock_prices(stock_code TEXT,trade_date TEXT,close REAL)')
                if codes:
                    rows = pg.execute('SELECT stock_code,trade_date,close FROM sector_market_prices '
                                      'WHERE stock_code=ANY(%s) AND trade_date >= %s AND close IS NOT NULL '
                                      'ORDER BY stock_code,trade_date', (codes, since))
                    db.executemany('INSERT INTO stock_prices VALUES (?,?,?)', rows)
                db.commit()
            def factory():
                conn = sqlite3.connect(uri, uri=True)
                conn.row_factory = sqlite3.Row
                conn.execute('PRAGMA query_only=ON')
                return conn

            def principles(conn):
                result = []
                for row in conn.execute('SELECT * FROM portfolio_principles ORDER BY id'):
                    rules = json.loads(row['rules_json'])
                    if any(rule.get('type') == 'max_exposure' for rule in rules):
                        raise ValueError('exposure data has not been projected')
                    result.append({'id': row['id'], 'text': row['text'], 'created_at': row['created_at'],
                                   'rules': [{**rule, 'summary': pp.describe(rule)} for rule in rules],
                                   'notes': json.loads(row['notes_json']) if row['notes_json'] else []})
                return result

            return get_portfolio(connection_factory=factory, principles_loader=principles)
        finally:
            db.close()

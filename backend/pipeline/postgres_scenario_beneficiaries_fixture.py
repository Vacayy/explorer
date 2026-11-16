"""Candidate-only scenario beneficiary projection using linked PG market data."""
import sqlite3
from datetime import date,timedelta
from pipeline.beneficiary import resolve_and_enrich
from pipeline.postgres_graph_fixture import _guard


class BeneficiarySnapshotConflict(ValueError):pass


def _generation(pg):
    row=pg.execute('''SELECT s.generation_id,m.generation_id,m.linked_document_generation
        FROM snapshot_metadata s CROSS JOIN sector_market_metadata m WHERE s.singleton AND m.singleton''').fetchone()
    if not row or not row[2] or row[0]!=row[1]:raise BeneficiarySnapshotConflict('Document and market generations differ')
    return row[0]


def import_beneficiary_aux(source,target):
    """Import only latest valuation rows and industry membership.

    Caller must use the SAME immutable SQLite backup that produced the linked
    document/market generation; count and date checks catch obvious mistakes,
    but do not independently prove backup identity.
    """
    _guard(target)
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0]!=1:
        raise ValueError('A query-only SQLite snapshot is required')
    generation=_generation(target)
    source_count,source_latest=source.execute('SELECT count(*),max(trade_date) FROM stock_prices').fetchone()
    pg_count,pg_latest=target.execute('SELECT count(*),max(trade_date) FROM sector_market_prices').fetchone()
    if (source_count,source_latest)!=(pg_count,pg_latest):raise BeneficiarySnapshotConflict('Market source counts or latest date differ')
    with target.transaction():
        target.execute('CREATE TABLE beneficiary_aux_metadata(singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),generation_id UUID NOT NULL)')
        target.execute('CREATE TABLE beneficiary_aux_fundamentals(stock_code TEXT NOT NULL,trade_date TEXT NOT NULL,per DOUBLE PRECISION,pbr DOUBLE PRECISION,PRIMARY KEY(stock_code,trade_date))')
        target.execute('CREATE TABLE beneficiary_aux_industry_groups(id BIGINT PRIMARY KEY,name TEXT NOT NULL)')
        target.execute('CREATE TABLE beneficiary_aux_industry_members(id BIGINT PRIMARY KEY,group_id BIGINT NOT NULL,stock_code TEXT NOT NULL)')
        with target.cursor() as cur:
            with cur.copy('COPY beneficiary_aux_fundamentals(stock_code,trade_date,per,pbr) FROM STDIN') as out:
                for row in source.execute('''SELECT f.stock_code,f.trade_date,f.per,f.pbr FROM fundamentals f
                    JOIN (SELECT stock_code,max(trade_date) d FROM fundamentals GROUP BY stock_code) x
                    ON x.stock_code=f.stock_code AND x.d=f.trade_date ORDER BY f.id'''):out.write_row(tuple(row))
            with cur.copy('COPY beneficiary_aux_industry_groups(id,name) FROM STDIN') as out:
                for row in source.execute('SELECT id,name FROM industry_groups ORDER BY id'):out.write_row(tuple(row))
            with cur.copy('COPY beneficiary_aux_industry_members(id,group_id,stock_code) FROM STDIN') as out:
                for row in source.execute('SELECT id,group_id,stock_code FROM industry_members ORDER BY id'):out.write_row(tuple(row))
        target.execute('INSERT INTO beneficiary_aux_metadata(generation_id) VALUES(%s)',(generation,))
    return {'fundamentals':target.execute('SELECT count(*) FROM beneficiary_aux_fundamentals').fetchone()[0],
            'industry_groups':target.execute('SELECT count(*) FROM beneficiary_aux_industry_groups').fetchone()[0],
            'industry_members':target.execute('SELECT count(*) FROM beneficiary_aux_industry_members').fetchone()[0]}


def resolve_beneficiaries(connect,picks):
    if not picks:return []
    with connect() as pg:
        pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');_guard(pg)
        generation=_generation(pg)
        aux=pg.execute('SELECT generation_id FROM beneficiary_aux_metadata WHERE singleton').fetchone()
        if not aux or aux[0]!=generation:raise BeneficiarySnapshotConflict('Beneficiary inputs belong to another generation')
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        try:
            db.executescript('''CREATE TABLE entities(id INTEGER,type TEXT,name TEXT,aliases TEXT);
                CREATE TABLE companies(stock_code TEXT,corp_name TEXT);
                CREATE TABLE industry_groups(id INTEGER,name TEXT);
                CREATE TABLE industry_members(id INTEGER,group_id INTEGER,stock_code TEXT);
                CREATE TABLE fundamentals(stock_code TEXT,trade_date TEXT,per REAL,pbr REAL);
                CREATE TABLE stock_prices(id INTEGER PRIMARY KEY,stock_code TEXT,trade_date TEXT,close REAL,market_cap REAL);
                CREATE INDEX stock_price_lookup ON stock_prices(stock_code,trade_date DESC);''')
            names=[p.get('name','').strip() for p in picks if isinstance(p.get('name'),str) and p.get('name','').strip()]
            if not names:return []
            # Include matching names and code aliases in source row order so
            # the original first-match behavior is retained.
            codes=[r[0] for r in pg.execute('''SELECT row_data->>'aliases' FROM legacy_snapshot_rows
                WHERE table_name='entities' AND row_data->>'type'='company' AND row_data->>'name'=ANY(%s)
                AND row_data->>'aliases' IS NOT NULL UNION SELECT stock_code FROM sector_market_companies
                WHERE corp_name=ANY(%s) AND stock_code IS NOT NULL''',(names,names))]
            entities=pg.execute('''SELECT row_data->>'id',row_data->>'type',row_data->>'name',row_data->>'aliases'
                FROM legacy_snapshot_rows WHERE table_name='entities' AND row_data->>'type'='company'
                AND (row_data->>'name'=ANY(%s) OR row_data->>'aliases'=ANY(%s)) ORDER BY row_ordinal''',(names,codes))
            db.executemany('INSERT INTO entities VALUES(?,?,?,?)',entities)
            db.executemany('INSERT INTO companies VALUES(?,?)',pg.execute('SELECT stock_code,corp_name FROM sector_market_companies WHERE corp_name=ANY(%s) ORDER BY ordinal',(names,)))
            db.executemany('INSERT INTO industry_groups VALUES(?,?)',pg.execute('SELECT id,name FROM beneficiary_aux_industry_groups ORDER BY id'))
            db.executemany('INSERT INTO industry_members VALUES(?,?,?)',pg.execute('SELECT id,group_id,stock_code FROM beneficiary_aux_industry_members WHERE stock_code=ANY(%s) ORDER BY id',(codes,)))
            db.executemany('INSERT INTO fundamentals VALUES(?,?,?,?)',pg.execute('SELECT stock_code,trade_date,per,pbr FROM beneficiary_aux_fundamentals WHERE stock_code=ANY(%s)',(codes,)))
            latest=pg.execute('SELECT max(trade_date) FROM sector_market_prices').fetchone()[0]
            if latest:
                prior=(date.fromisoformat(latest)-timedelta(days=30)).isoformat()
                rows=pg.execute('''WITH snapshot AS (
                  (SELECT DISTINCT ON(stock_code) id,stock_code,trade_date,close,market_cap FROM sector_market_prices
                   WHERE trade_date<=%s AND close IS NOT NULL ORDER BY stock_code,trade_date DESC)
                  UNION
                  (SELECT DISTINCT ON(stock_code) id,stock_code,trade_date,close,market_cap FROM sector_market_prices
                   WHERE trade_date<=%s AND close IS NOT NULL ORDER BY stock_code,trade_date DESC)),
                  selected AS (SELECT id,stock_code,trade_date,close,market_cap,
                    row_number() OVER(PARTITION BY stock_code ORDER BY trade_date DESC) rn FROM sector_market_prices
                    WHERE stock_code=ANY(%s) AND close IS NOT NULL)
                  SELECT id,stock_code,trade_date,close,market_cap FROM snapshot
                  UNION SELECT id,stock_code,trade_date,close,market_cap FROM selected WHERE rn<=250''',(latest,prior,codes))
                db.executemany('INSERT INTO stock_prices VALUES(?,?,?,?,?)',rows)
                if db.execute('SELECT max(trade_date) FROM stock_prices').fetchone()[0]!=latest:
                    db.execute("INSERT INTO stock_prices VALUES(-1,'',?,NULL,NULL)",(latest,))
            return resolve_and_enrich(db,picks)
        finally:db.close()

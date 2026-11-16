"""Member-scoped portfolio experiment for disposable PostgreSQL schemas only.

The caller must supply a verified internal principal; this module is not an
authentication boundary and is never registered with the running service.
"""
from datetime import date, timedelta
from contextlib import contextmanager
import psycopg
from models.portfolio import TransactionCreate
from pipeline.portfolio import EPS, LedgerError, history_from_source, replay, summary_from_source
from pipeline.postgres_graph_fixture import _guard


def initialize(conn):
    _guard(conn)
    conn.execute('''CREATE TABLE fixture_portfolio_accounts (
        principal TEXT PRIMARY KEY CHECK (principal <> ''),
        id BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE NOT NULL)''')
    conn.execute('''CREATE TABLE fixture_portfolio_transactions (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        account_id BIGINT NOT NULL REFERENCES fixture_portfolio_accounts(id),
        trade_date TEXT NOT NULL, kind TEXT NOT NULL,
        stock_code TEXT, amount DOUBLE PRECISION NOT NULL CHECK(amount > 0),
        price DOUBLE PRECISION, note TEXT NOT NULL DEFAULT '')''')
    conn.execute('''CREATE TABLE fixture_portfolio_members (
        account_id BIGINT NOT NULL REFERENCES fixture_portfolio_accounts(id),
        stock_code TEXT NOT NULL, bought_at TEXT NOT NULL,
        PRIMARY KEY(account_id,stock_code))''')
    conn.execute('''CREATE TABLE fixture_portfolio_legacy_mapping (
        legacy_group_id BIGINT PRIMARY KEY,
        account_id BIGINT UNIQUE NOT NULL REFERENCES fixture_portfolio_accounts(id))''')
    conn.execute('''CREATE TABLE fixture_portfolio_principles (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        account_id BIGINT NOT NULL REFERENCES fixture_portfolio_accounts(id),
        text TEXT NOT NULL,rules_json TEXT NOT NULL,notes_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'))''')


def _account(conn, principal, *, create=False):
    _guard(conn)
    if not isinstance(principal,str) or not principal.strip():
        raise ValueError('Verified principal required')
    if create:
        conn.execute('INSERT INTO fixture_portfolio_accounts(principal) VALUES (%s) ON CONFLICT DO NOTHING',(principal,))
    row=conn.execute('SELECT id FROM fixture_portfolio_accounts WHERE principal=%s FOR UPDATE',(principal,)).fetchone()
    return row[0] if row else None


def _transactions(conn, account):
    return [dict(zip(('id','trade_date','kind','stock_code','amount','price'),row)) for row in
            conn.execute('SELECT id,trade_date,kind,stock_code,amount,price FROM fixture_portfolio_transactions '
                         'WHERE account_id=%s ORDER BY trade_date,id',(account,))]


def _sync_members(conn, account, ledger):
    for code,position in ledger.positions.items():
        conn.execute('INSERT INTO fixture_portfolio_members(account_id,stock_code,bought_at) VALUES (%s,%s,%s) '
                     'ON CONFLICT(account_id,stock_code) DO UPDATE SET bought_at=excluded.bought_at',
                     (account,code,position.entry_date))
    conn.execute('DELETE FROM fixture_portfolio_members WHERE account_id=%s AND NOT (stock_code=ANY(%s))',
                 (account,list(ledger.positions)))


def map_archived_portfolio(conn, principal, legacy_group_id):
    """Explicitly map one archived fixture group; never infer an owner."""
    _guard(conn)
    if not isinstance(legacy_group_id,int) or isinstance(legacy_group_id,bool) or legacy_group_id<=0:
        raise ValueError('Explicit legacy group required')
    required=['stock_groups','stock_group_members','portfolio_transactions','portfolio_quotes']
    if conn.execute('SELECT count(*) FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(required,)).fetchone()[0] != len(required):
        raise ValueError('Complete portfolio snapshot required')
    # Prevent concurrent inserts while retaining legacy IDs and advancing the
    # destination sequence. The archive itself remains unchanged.
    account=_account(conn,principal,create=True)
    conn.execute('LOCK TABLE fixture_portfolio_transactions IN EXCLUSIVE MODE')
    if _transactions(conn,account) or conn.execute('SELECT 1 FROM fixture_portfolio_legacy_mapping WHERE account_id=%s OR legacy_group_id=%s',
                                                  (account,legacy_group_id)).fetchone():
        raise ValueError('Portfolio or legacy group already mapped')
    group=conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='stock_groups' AND row_data->>'id'=%s",(str(legacy_group_id),)).fetchall()
    if len(group)!=1 or group[0][0].get('kind')!='portfolio':
        raise ValueError('Legacy portfolio group unavailable')
    rows=[row for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='portfolio_transactions' "
        "AND row_data->>'group_id'=%s ORDER BY row_data->>'trade_date',(row_data->>'id')::bigint",(str(legacy_group_id),))]
    ledger=replay(rows)
    for row in rows:
        conn.execute('INSERT INTO fixture_portfolio_transactions(id,account_id,trade_date,kind,stock_code,amount,price,note) '
            'OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (row['id'],account,row['trade_date'],row['kind'],row.get('stock_code'),row['amount'],row.get('price'),row.get('note') or ''))
    if rows:
        conn.execute("SELECT setval(pg_get_serial_sequence('fixture_portfolio_transactions','id'), "
                     "GREATEST((SELECT max(id) FROM fixture_portfolio_transactions),"
                     "(SELECT last_value FROM fixture_portfolio_transactions_id_seq),1),TRUE)")
    _sync_members(conn,account,ledger)
    conn.execute('INSERT INTO fixture_portfolio_legacy_mapping VALUES (%s,%s)',(legacy_group_id,account))


def list_transactions(conn, principal, *, names):
    rows=_transactions(conn,_account(conn,principal))
    return [{'id':t['id'],'trade_date':t['trade_date'],'kind':t['kind'],'stock_code':t['stock_code'],
             'name':names.get(t['stock_code'],t['stock_code']) if t['stock_code'] else None,'price':t['price']}
            for t in reversed(rows)]


class FixturePortfolioReadSource:
    """Use member transactions with explicitly supplied shared market data."""
    def __init__(self, conn, principal, *, names, prices):
        if not callable(prices):
            raise ValueError('Explicit market price provider required')
        self.conn=conn
        self.account=_account(conn,principal)
        self._names=names
        self._prices=prices

    def transactions(self):
        return _transactions(self.conn,self.account)

    def names(self, codes):
        return {code:self._names[code] for code in codes if code in self._names}

    def prices(self, txs, ledger):
        return self._prices(txs,ledger)


class FixturePortfolioMarket:
    """Stored shared prices from the existing sector snapshot, no network."""
    def __init__(self, conn):
        _guard(conn)
        if not conn.execute('SELECT 1 FROM sector_market_metadata LIMIT 1').fetchone():
            raise ValueError('Sector market snapshot required')
        self.conn=conn

    def names(self):
        return dict(self.conn.execute('SELECT stock_code,corp_name FROM sector_market_companies WHERE corp_name IS NOT NULL'))

    def last_close(self, code, day):
        row=self.conn.execute('SELECT close FROM sector_market_prices WHERE stock_code=%s AND trade_date<=%s AND close IS NOT NULL '
                              'ORDER BY trade_date DESC LIMIT 1',(code,day)).fetchone()
        return float(row[0]) if row else None

    def prices(self, txs, ledger):
        codes={row['stock_code'] for row in txs if row['stock_code']}
        if not codes:
            return {},{}
        since=(date.fromisoformat(txs[0]['trade_date'])-timedelta(days=14)).isoformat()
        series={}
        for code,day,close in self.conn.execute('SELECT stock_code,trade_date,close FROM sector_market_prices '
                'WHERE stock_code=ANY(%s) AND trade_date >= %s AND close IS NOT NULL ORDER BY stock_code,trade_date',
                (list(codes),since)):
            series.setdefault(code,[]).append((day,float(close)))
        # Intraday quotes have a separate capture and freshness contract.
        return series,{}


def read_portfolio(conn, principal, *, names, prices):
    source=FixturePortfolioReadSource(conn,principal,names=names,prices=prices)
    return {'summary':summary_from_source(source),'history':history_from_source(source),
            'transactions':list_transactions(conn,principal,names=names)}


def add_transaction(conn, principal, raw, *, companies, last_close):
    """Validate and write one account under its row lock; caller owns transaction."""
    tx=TransactionCreate.model_validate(raw).model_dump()
    account=_account(conn,principal,create=True)
    if tx['kind'] in ('buy','sell'):
        if not tx.get('stock_code'):
            raise LedgerError('종목을 선택하세요.')
        if tx['stock_code'] not in companies:
            raise LedgerError('알 수 없는 종목입니다.')
        if not tx.get('price'):
            tx['price']=last_close(tx['stock_code'],tx['trade_date'])
            if not tx['price']:
                raise LedgerError('체결가를 입력하세요(저장된 종가 없음).')
    else:
        tx['stock_code'],tx['price']=None,None
    existing=_transactions(conn,account)
    if tx['sell_all']:
        position=replay([row for row in existing if row['trade_date'] <= tx['trade_date']]).positions.get(tx['stock_code'])
        if not position:
            raise LedgerError(f"{tx['trade_date']}에 보유하지 않은 종목입니다.")
        tx['amount']=position.qty*tx['price']
    pending=[]
    if tx['kind']=='buy' and tx['fund_shortfall']:
        cash=replay([row for row in existing if row['trade_date'] <= tx['trade_date']]).cash
        if tx['amount'] > cash+EPS:
            pending.append({'kind':'deposit','amount':tx['amount']-cash,'stock_code':None,'price':None,
                            'trade_date':tx['trade_date'],'note':'매수 부족분 자동 입금'})
    pending.append(tx)
    next_id=max((row['id'] for row in existing),default=0)+1
    ledger=replay(existing+[{**item,'id':next_id+i} for i,item in enumerate(pending)])
    for item in pending:
        ident=conn.execute('INSERT INTO fixture_portfolio_transactions(account_id,trade_date,kind,stock_code,amount,price,note) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (account,item['trade_date'],item['kind'],item['stock_code'],item['amount'],item['price'],item.get('note') or '')).fetchone()[0]
    _sync_members(conn,account,ledger)
    return ident


def delete_transaction(conn, principal, ident):
    account=_account(conn,principal)
    if account is None:
        return False
    rows=_transactions(conn,account)
    if not any(row['id']==ident for row in rows):
        return False
    ledger=replay([row for row in rows if row['id'] != ident])
    conn.execute('DELETE FROM fixture_portfolio_transactions WHERE account_id=%s AND id=%s',(account,ident))
    _sync_members(conn,account,ledger)
    return True


class MemberPortfolioFixture:
    """Adapter for the existing member router; fixture DB and principal only.

    Authentication, CSRF and HTTP error handling belong to the existing router
    and access boundary. The caller supplies their transaction-unavailable type.
    """
    def __init__(self, factory, principal, *, names, prices, last_close, unavailable):
        if not isinstance(principal,str) or not principal.strip():
            raise ValueError('Verified principal required')
        self.factory,self.owner=factory,principal
        self.names,self.prices,self.last_close=names,prices,last_close
        self.unavailable=unavailable

    @contextmanager
    def connection(self):
        try:
            with self.factory() as conn:
                yield conn
        except psycopg.Error:
            # Existing member router maps storage failures to a sanitized 503.
            raise OSError('Portfolio storage unavailable') from None

    def read(self, operation):
        from pipeline import portfolio as legacy
        with self.connection() as conn:
            source=FixturePortfolioReadSource(conn,self.owner,names=self.names,prices=self.prices)
            if operation is legacy.summary:
                return legacy.summary_from_source(source)
            if operation is legacy.history:
                return legacy.history_from_source(source)
            if operation is legacy.transactions:
                return list_transactions(conn,self.owner,names=self.names)
            raise ValueError('Unsupported portfolio operation')

    def add(self, body):
        with self.connection() as conn:
            return add_transaction(conn,self.owner,body.model_dump(),companies=set(self.names),last_close=self.last_close)

    def delete(self, ident):
        with self.connection() as conn:
            if not delete_transaction(conn,self.owner,ident):
                raise self.unavailable()

    def companies(self, query):
        query=query.strip()
        if not query:
            return []
        return [{'stock_code':code,'corp_name':name} for code,name in sorted(self.names.items())
                if query in code or query in name][:20]


class MemberPrinciplesFixture:
    """Use the existing member principle validation with an isolated owner."""
    def __init__(self, portfolio):
        self.portfolio=portfolio

    def listing(self):
        from security.member_principles import MemberPrinciples
        with self.portfolio.connection() as conn:
            account=_account(conn,self.portfolio.owner)
            rows=conn.execute('SELECT id,text,rules_json,notes_json,created_at FROM fixture_portfolio_principles '
                              'WHERE account_id=%s ORDER BY id',(account,)).fetchall()
            return [MemberPrinciples.projection(dict(zip(('id','text','rules_json','notes_json','created_at'),row))) for row in rows]

    def create(self, body):
        from security.member_principles import MemberPrinciples, PrincipleLimit
        values=MemberPrinciples.cleaned(body)
        with self.portfolio.connection() as conn:
            account=_account(conn,self.portfolio.owner,create=True)
            if conn.execute('SELECT count(*) FROM fixture_portfolio_principles WHERE account_id=%s',(account,)).fetchone()[0]>=100:
                raise PrincipleLimit()
            return conn.execute('INSERT INTO fixture_portfolio_principles(account_id,text,rules_json,notes_json) '
                                'VALUES (%s,%s,%s,%s) RETURNING id',(account,*values)).fetchone()[0]

    def _change(self, ident, sql, params=()):
        from security.member_principles import PrincipleUnavailable
        with self.portfolio.connection() as conn:
            account=_account(conn,self.portfolio.owner)
            if account is None or not conn.execute(sql,(*params,ident,account)).rowcount:
                raise PrincipleUnavailable()

    def replace(self, ident, body):
        from security.member_principles import MemberPrinciples
        self._change(ident,'UPDATE fixture_portfolio_principles SET text=%s,rules_json=%s,notes_json=%s WHERE id=%s AND account_id=%s',
                     MemberPrinciples.cleaned(body))

    def update_text(self, ident, text):
        self._change(ident,'UPDATE fixture_portfolio_principles SET text=%s WHERE id=%s AND account_id=%s',(text,))

    def delete(self, ident):
        self._change(ident,'DELETE FROM fixture_portfolio_principles WHERE id=%s AND account_id=%s')

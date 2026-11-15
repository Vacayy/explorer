"""Member-owned confirmed principles; no legacy schema, parser or alert side effects."""
import json
import math
from pipeline import portfolio_principles as rules, portfolio as pf
from datetime import datetime
from zoneinfo import ZoneInfo
from security.member_portfolio import MemberPortfolio


class PrincipleUnavailable(Exception):
    pass


class PrincipleInvalid(Exception):
    pass


class PrincipleLimit(Exception):
    pass


class MemberPrinciples(MemberPortfolio):
    @staticmethod
    def prepared(conn):
        conn.execute('SELECT group_id,text,rules_json,notes_json FROM member_portfolio_principles LIMIT 0')

    @staticmethod
    def projection(row):
        return {'id': row['id'], 'text': row['text'], 'created_at': row['created_at'],
                'rules': [{**rule, 'summary': rules.describe(rule)} for rule in json.loads(row['rules_json'])],
                'notes': json.loads(row['notes_json'])}

    @staticmethod
    def cleaned(body):
        try:
            clean = rules.validate([rule.model_dump(exclude={'summary'}) for rule in body.rules])
            notes = rules._clean_notes(body.notes)
            if not clean and not notes:
                raise ValueError()
            return body.text, json.dumps(clean), json.dumps(notes, ensure_ascii=False)
        except (ValueError, TypeError, KeyError):
            raise PrincipleInvalid() from None

    def listing(self):
        with self.connection() as conn:
            self.prepared(conn)
            return [self.projection(row) for row in conn.execute(
                'SELECT id,text,rules_json,notes_json,created_at FROM member_portfolio_principles WHERE group_id=? ORDER BY id',
                (self.group(conn),))]

    def evaluate(self):
        with self.connection() as conn:
            self.prepared(conn)
            gid = self.group(conn)
            items = [self.projection(row) for row in conn.execute(
                'SELECT id,text,rules_json,notes_json,created_at FROM member_portfolio_principles WHERE group_id=? ORDER BY id', (gid,))]
            summary = pf.summary(conn, gid=gid)
            peak_prices = {}
            if any(rule['type'] == 'peak_exit' for item in items for rule in item['rules']):
                candidates = [h for h in summary.get('holdings', []) if h.get('entry_date') and h.get('last_close') is not None]
                # The shared loader drops nonpositive/null rows. Reject corrupt
                # stored inputs before that filtering (or conversion of text).
                candidates = [h for h in candidates if not conn.execute(
                    "SELECT 1 FROM stock_prices WHERE stock_code=? AND trade_date >= date(?, '-400 days') "
                    "AND (typeof(close) NOT IN ('integer','real') OR close <= 0) LIMIT 1",
                    (h['code'], h['entry_date'])).fetchone()]
                loaded = rules.load_prices(conn, candidates)
                peak_prices = {h['code']: loaded[h['code']] for h in candidates
                               if peak_input_ready(loaded.get(h['code']), h['last_close'])}
            coverage, violations = [], []
            today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
            for item in items:
                for index, rule in enumerate(item['rules']):
                    status, reason = rule_coverage(rule['type'], summary)
                    if rule['type'] == 'peak_exit':
                        status, reason = peak_coverage(summary.get('holdings', []), peak_prices)
                    coverage.append({'principle_id':item['id'], 'rule_index':index,
                                     'rule':rules.describe(rule), 'status':status, 'reason':reason})
                    if status not in ('evaluated', 'partial'):
                        continue
                    field = HOLDING_FIELDS.get(rule['type'])
                    eligible = [h for h in summary.get('holdings', []) if field is None or h.get(field) is not None]
                    if rule['type'] == 'peak_exit':
                        eligible = [h for h in eligible if h['code'] in peak_prices]
                    inputs = {**summary, 'holdings': eligible}
                    for hit in rules.violations([{**item, 'rules':[rule]}], inputs, today=today, prices=peak_prices):
                        # The engine sees one rule; preserve its original index in the response key.
                        suffix = hit['key'].split(':', 2)[2]
                        hit['key'] = f"{item['id']}:{index}:{suffix}"
                        violations.append({k:hit[k] for k in ('key','principle_id','rule','message')})
            return {'as_of':summary.get('quoted_at') or summary.get('as_of'), 'rules':len(coverage),
                    'coverage':coverage, 'notifications_enabled':False,
                    'price_dates':sorted({h['last_date'] for h in summary.get('holdings', []) if h.get('last_date')}),
                    'items':violations}

    def create(self, body):
        values = self.cleaned(body)
        with self.connection(write=True) as conn:
            self.prepared(conn)
            gid = self.group(conn, create=True)
            if conn.execute('SELECT COUNT(*) FROM member_portfolio_principles WHERE group_id=?', (gid,)).fetchone()[0] >= 100:
                raise PrincipleLimit()
            return conn.execute('INSERT INTO member_portfolio_principles(group_id,text,rules_json,notes_json) VALUES(?,?,?,?)',
                                (gid, *values)).lastrowid

    def replace(self, principle_id, body):
        values = self.cleaned(body)
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('UPDATE member_portfolio_principles SET text=?,rules_json=?,notes_json=? WHERE id=? AND group_id=?',
                                (*values, principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()

    def update_text(self, principle_id, text):
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('UPDATE member_portfolio_principles SET text=? WHERE id=? AND group_id=?',
                                (text, principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()

    def delete(self, principle_id):
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('DELETE FROM member_portfolio_principles WHERE id=? AND group_id=?',
                                (principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()


HOLDING_FIELDS = {'max_weight': 'weight_pct', 'stop_loss': 'return_pct', 'take_profit': 'return_pct',
                  'day_drop': 'day_change_pct', 'max_holding_days': 'entry_date'}

def rule_coverage(kind, summary):
    holdings = summary.get('holdings', [])
    deferred = {'max_exposure': 'Shared exposure evidence is not connected',
                'peak_exit': 'Complete peak-exit price history is not verified',
                'max_entry_weight': 'Historical entry valuation is not verified',
                'account_drawdown': 'Complete historical account valuation is not verified'}
    if kind in deferred:
        return 'unavailable', deferred[kind]
    if kind == 'max_holdings':
        return 'evaluated', None
    if kind in ('min_cash', 'max_cash', 'max_weight'):
        if any(h.get('last_close') is None for h in holdings):
            return 'unavailable', 'Some holdings have no stored price'
        field = 'cash_weight_pct' if kind != 'max_weight' else None
        if field and summary.get(field) is None:
            return 'unavailable', 'Account valuation is unavailable'
    if not holdings and kind not in ('min_cash', 'max_cash'):
        return 'not_applicable', 'No current holdings'
    if kind in HOLDING_FIELDS:
        available = sum(h.get(HOLDING_FIELDS[kind]) is not None for h in holdings)
        if available == 0:
            return 'unavailable', 'Required holding inputs are unavailable'
        if available < len(holdings):
            return 'partial', 'Only holdings with complete inputs were evaluated'
    return 'evaluated', None


def peak_input_ready(prices, last_close):
    if not prices or prices.get('market') not in ('KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL', 'KONEX'):
        return False
    closes, start = prices['closes'], prices['start']
    # The existing shoulder search uses 252 stored observations before a peak.
    # Requiring them before entry supports every possible held-period peak.
    return (252 <= start < len(closes) and len(closes) >= rules.EXIT_MA
            and all(math.isfinite(value) and value > 0 for value in closes)
            and closes[-1] == last_close)


def peak_coverage(holdings, prices):
    if not holdings:
        return 'not_applicable', 'No current holdings'
    available = sum(h['code'] in prices for h in holdings)
    if available == 0:
        return 'unavailable', 'Peak-exit requires market and at least 252 stored prices before entry'
    if available < len(holdings):
        return 'partial', 'Only holdings with verified peak-exit inputs were evaluated'
    return 'evaluated', None

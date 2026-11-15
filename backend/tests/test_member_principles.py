"""Ownership is enforced in the actual member routes; legacy jobs remain separate."""
import unittest
from unittest.mock import patch
from tests import test_member_portfolio as fixture
from pipeline import portfolio_principles as legacy


class MemberPrincipleTests(unittest.TestCase):
    setUp = fixture.MemberPortfolioTests.setUp
    connect = fixture.MemberPortfolioTests.connect

    def create(self, member='a', **changes):
        return self.client.post(self.base+'/principles', headers=self.headers[member], json={
            'text':'member private principle', 'rules':[{'type':'max_weight','params':{'pct':25}}],
            'notes':['member private note'], **changes})

    def test_read_is_empty_and_has_no_schema_or_group_side_effect(self):
        before=self.path.read_bytes()
        for name in self.users:
            r=self.client.get(self.base+'/principles',headers=self.headers[name])
            self.assertEqual(r.status_code,200);self.assertEqual(r.json(),[])
        self.assertEqual(before,self.path.read_bytes())

    def test_other_member_and_operator_cannot_read_edit_or_delete(self):
        created=self.create();self.assertEqual(created.status_code,201,created.text)
        pid=created.json()['id'];url=self.base+'/principles/'+str(pid)
        for member in ('b','operator'):
            self.assertEqual(self.client.get(self.base+'/principles',headers=self.headers[member]).json(),[])
            self.assertEqual(self.client.patch(url,headers=self.headers[member],json={'text':'foreign change'}).status_code,404)
            self.assertEqual(self.client.put(url,headers=self.headers[member],json={'text':'foreign change','notes':['note']}).status_code,404)
            self.assertEqual(self.client.delete(url,headers=self.headers[member]).status_code,404)
        self.assertEqual(self.client.patch(url,headers=self.headers['a'],json={'text':'updated private text'}).status_code,200)
        stored=self.client.get(self.base+'/principles',headers=self.headers['a']).json()[0]
        self.assertEqual(stored['text'],'updated private text')
        self.assertEqual(stored['rules'][0]['params'],{'pct':25.0})
        self.assertEqual(self.client.put(url,headers=self.headers['a'],json={'text':'replacement text','notes':['replacement note']}).status_code,200)
        self.assertEqual(self.client.delete(url,headers=self.headers['a']).status_code,200)

    def test_anonymous_csrf_and_owner_injection_rejected(self):
        self.assertEqual(self.client.get(self.base+'/principles').status_code,401)
        headers=dict(self.headers['a']);headers.pop('X-CSRF-Token')
        self.assertEqual(self.client.post(self.base+'/principles',headers=headers,json={'text':'secret input'}).status_code,403)
        r=self.create(owner_id=self.users['b']);self.assertEqual(r.status_code,422)
        self.assertNotIn(self.users['b'],r.text)
        r=self.create(notes=['PRIVATE_CANARY'*100]);self.assertEqual(r.status_code,422)
        self.assertNotIn('PRIVATE_CANARY',r.text)
        r=self.create(rules=[{'type':'PRIVATE_BAD_RULE','params':{}}]);self.assertEqual(r.status_code,422)
        self.assertNotIn('PRIVATE_BAD_RULE',r.text)

    def test_legacy_principles_and_scheduler_inputs_stay_separate(self):
        with self.connect() as conn:
            legacy.add(conn,'legacy operator canary',[{'type':'max_weight','params':{'pct':40}}])
            before=legacy.principles(conn)
        with patch.object(legacy,'parse',side_effect=AssertionError('provider')), patch.object(legacy,'ensure_schema',side_effect=AssertionError('legacy schema')):
            self.assertEqual(self.create().status_code,201)
            r=self.client.get(self.base+'/principles',headers=self.headers['a'])
            self.assertNotIn('legacy operator canary',r.text)
        with self.connect() as conn:self.assertEqual(legacy.principles(conn),before)

    def test_unprepared_schema_fails_without_auto_creation(self):
        with self.connect() as conn:conn.execute('DROP TABLE member_portfolio_principles')
        before=self.path.read_bytes()
        self.assertEqual(self.client.get(self.base+'/principles',headers=self.headers['a']).status_code,503)
        self.assertEqual(self.path.read_bytes(),before)

    def test_per_owner_limit_does_not_consume_other_members_capacity(self):
        self.assertEqual(self.create().status_code,201)
        with self.connect() as conn:
            row=conn.execute('SELECT group_id,text,rules_json,notes_json FROM member_portfolio_principles').fetchone()
            conn.executemany('INSERT INTO member_portfolio_principles(group_id,text,rules_json,notes_json) VALUES(?,?,?,?)', [tuple(row)]*99)
        self.assertEqual(self.create().status_code,409)
        self.assertEqual(self.create('b').status_code,201)

    def test_evaluation_uses_only_own_portfolio_and_never_legacy_alerts(self):
        self.assertEqual(self.create().status_code,201)
        self.assertEqual(self.create('b').status_code,201)
        fixture.MemberPortfolioTests.add(self, name='a')
        before=self.path.read_bytes()
        with patch.object(legacy,'current',side_effect=AssertionError('legacy current')), \
                patch.object(legacy,'alert',side_effect=AssertionError('alert')):
            a=self.client.get(self.base+'/principles/state',headers=self.headers['a'])
            b=self.client.get(self.base+'/principles/state',headers=self.headers['b'])
        self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(a.json()['coverage'][0]['status'],'evaluated')
        self.assertEqual(len(a.json()['items']),1)
        self.assertFalse(a.json()['notifications_enabled'])
        self.assertEqual(b.json()['items'],[])
        self.assertEqual(b.json()['coverage'][0]['status'],'not_applicable')
        self.assertNotIn('member private principle',a.text)
        self.assertEqual(before,self.path.read_bytes())

    def test_missing_quotes_and_deferred_inputs_are_not_reported_as_pass(self):
        self.assertEqual(self.create(rules=[{'type':'max_weight','params':{'pct':25}},
                                         {'type':'max_exposure','params':{'pct':25}}]).status_code,201)
        fixture.MemberPortfolioTests.add(self,name='a',stock_code='BBBBBB')
        r=self.client.get(self.base+'/principles/state',headers=self.headers['a'])
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([x['status'] for x in r.json()['coverage']],['unavailable','unavailable'])
        self.assertEqual(r.json()['items'],[])

    def test_mixed_price_coverage_is_partial_with_only_known_violations(self):
        self.assertEqual(self.create(rules=[{'type':'take_profit','params':{'pct':5}}]).status_code,201)
        fixture.MemberPortfolioTests.add(self,name='a')
        fixture.MemberPortfolioTests.add(self,name='a',stock_code='BBBBBB')
        r=self.client.get(self.base+'/principles/state',headers=self.headers['a'])
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['coverage'][0]['status'],'partial')
        self.assertEqual(len(r.json()['items']),1)
        self.assertNotIn('BBBBBB',r.json()['items'][0]['message'])

    def test_incomplete_holding_is_not_executed_and_original_rule_index_survives(self):
        self.assertEqual(self.create(rules=[{'type':'max_exposure','params':{'pct':25}},
                                         {'type':'max_holding_days','params':{'days':1}}]).status_code,201)
        summary={'as_of':'2026-01-01','holdings':[
            {'code':'KNOWN','name':'known','entry_date':'2020-01-01'},
            {'code':'MISSING','name':'missing','entry_date':None}]}
        with patch('security.member_principles.pf.summary', return_value=summary), \
                patch.object(legacy,'violations',wraps=legacy.violations) as evaluate:
            r=self.client.get(self.base+'/principles/state',headers=self.headers['a'])
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([x['status'] for x in r.json()['coverage']],['unavailable','partial'])
        self.assertEqual(len(r.json()['items']),1)
        self.assertEqual(r.json()['items'][0]['key'].split(':')[1],'1')
        self.assertEqual(evaluate.call_count,1)
        self.assertEqual([h['code'] for h in evaluate.call_args.args[1]['holdings']],['KNOWN'])

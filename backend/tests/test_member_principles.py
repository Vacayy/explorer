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

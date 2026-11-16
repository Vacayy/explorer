from contextlib import closing
from pathlib import Path
from datetime import date
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import spine_actions as actions
from security import public_actions as public
from security.access_boundary import PublicAccessBoundary


class PublicActionTests(unittest.TestCase):
    def test_stored_originals_corrections_and_rights_without_private_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'public.sqlite'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE corporate_actions ('+','.join(actions.ACTION_COLUMNS)+',private_note)')
                conn.execute('CREATE TABLE capital_raise_details ('+','.join(actions.RIGHTS_COLUMNS)+',raw_private)')
                conn.executescript("CREATE TABLE stock_prices(stock_code,trade_date,close); CREATE TABLE public_actions_metadata(as_of); INSERT INTO public_actions_metadata VALUES ('2026-11-13T09:00:00Z'); CREATE TABLE stock_groups(secret);")
                day=date.today().strftime('%Y%m%d')
                for i,title in [(1,'유상증자결정'),(2,'[정정]유상증자결정')]:
                    conn.execute('INSERT INTO corporate_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(i,str(i),'Example','000001','Y','유상증자',title,day,1e12,'Stored public summary.','private-canary'))
                row={k:None for k in actions.RIGHTS_COLUMNS};row.update(rcp_no='1',stock_code='000001',corp_name='Example',action_type='유상증자',method='주주배정',price_final=100,old_shares=1000,new_shares=100)
                conn.execute('INSERT INTO capital_raise_details VALUES ('+','.join('?' for _ in range(len(row)+1))+')',(*row.values(),'private-canary'))
                conn.execute("INSERT INTO stock_prices VALUES ('000001','2026-11-13',110)");conn.commit()
            before=path.read_bytes()
            with patch.object(actions,'my_groups',side_effect=AssertionError('private groups')),patch.object(actions,'_scanned_at',side_effect=AssertionError('job logs')):
                original=public.actions(kind='original',path=path)
                self.assertEqual(original.total,1);self.assertIsNone(original.items[0].my_group)
                self.assertEqual(original.counts.correction,1)
                self.assertEqual(public.actions(kind='correction',path=path).items[0].id,2)
                rights=public.rights(path=path);self.assertEqual(rights.items[0].diff_pct,10);self.assertEqual(rights.items[0].ratio_pct,10)
                self.assertNotIn('canary',rights.model_dump_json()+original.model_dump_json())
            self.assertEqual(before,path.read_bytes())
            with closing(public.connection(path)) as conn:
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('SELECT private_note FROM corporate_actions')
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('DELETE FROM corporate_actions')
            app=FastAPI();app.include_router(actions.router)
            app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/actions'+s):'public' for s in ('','/rights')})
            with TestClient(app,base_url='https://beta.example') as client,patch.object(public,'DB_PATH',path):
                self.assertEqual(client.get('/api/spine/actions?kind=original').status_code,200)
                self.assertEqual(client.get('/api/spine/actions/rights').status_code,200)
                self.assertEqual(client.get('/api/spine/actions?days=181').status_code,422)

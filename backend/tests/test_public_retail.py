from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_retail_heat import db
from pipeline import retail_heat as rh
from routers import spine_retail
from security import public_retail as public
from security.access_boundary import PublicAccessBoundary


class PublicRetailTests(unittest.TestCase):
    def test_original_calculations_without_ddl_or_collector_config(self):
        with tempfile.TemporaryDirectory() as tmp, closing(db()) as source:
            with patch.object(rh,'krx_configured',return_value=False): expected=rh.summary(source)
            expected_history=rh.history(source,10000)
            rh.save_snapshots(source);expected_snapshots=rh.snapshots(source)
            path=Path(tmp)/'public.sqlite'
            with closing(sqlite3.connect(path)) as target:
                source.backup(target)
                target.execute('CREATE TABLE secrets(value TEXT)');target.commit()
            before=path.read_bytes()
            with patch.object(rh,'ensure_schema',side_effect=AssertionError('DDL')),patch.object(rh,'krx_configured',side_effect=AssertionError('config')):
                self.assertEqual(public.summary(path=path),expected)
                self.assertEqual(public.history(10000,path=path)['points'],expected_history)
                self.assertEqual(public.snapshots(path=path),expected_snapshots)
            self.assertEqual(before,path.read_bytes())
            with closing(public.connection(path)) as conn:
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('SELECT value FROM secrets')
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('DELETE FROM retail_flows')
            app=FastAPI();app.include_router(spine_retail.router)
            app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={
                ('GET','/api/spine/retail'+suffix):'public' for suffix in ('','/history','/snapshots')})
            with TestClient(app,base_url='https://beta.example') as client,patch.object(public,'DB_PATH',path):
                for suffix in ('','/history?days=10000','/snapshots'):
                    self.assertEqual(client.get('/api/spine/retail'+suffix).status_code,200)
                self.assertEqual(client.get('/api/spine/retail/history?days=10001').status_code,422)

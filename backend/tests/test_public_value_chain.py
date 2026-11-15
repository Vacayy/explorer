"""Read-only market snapshot and company filters."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from security.public_value_chain import stored


class PublicValueChainTests(unittest.TestCase):
    def test_snapshot_filter_and_private_tables_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'snapshot.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE public_value_chain_snapshot(name TEXT PRIMARY KEY,payload TEXT)')
                conn.executemany('INSERT INTO public_value_chain_snapshot VALUES (?,?)', [
                    ('links', json.dumps({'as_of':'2026-10','items':[{'kr_code':'111111'},{'kr_code':'222222'}]})),
                    ('confirm', json.dumps([{'stock_code':'111111'},{'stock_code':'222222'}])),
                ])
                conn.execute("CREATE TABLE private_records(secret TEXT)")
                conn.execute("INSERT INTO private_records VALUES ('private-canary')")
            before = path.read_bytes()
            self.assertEqual(stored('links','111111',path=path)['items'], [{'kr_code':'111111'}])
            self.assertEqual(stored('confirm','222222',path=path), [{'stock_code':'222222'}])
            self.assertNotIn('private-canary', str(stored('links',path=path)))
            with self.assertRaises(LookupError): stored('confirm','999999',path=path)
            with self.assertRaises(ValueError): stored('private_records',path=path)
            self.assertEqual(path.read_bytes(), before)

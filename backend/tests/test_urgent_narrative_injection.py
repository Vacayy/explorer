"""Existing urgent selection with explicitly isolated dependencies."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from pipeline.narrative import compute_urgent_narratives


class UrgentNarrativeInjectionTests(unittest.TestCase):
    def test_selection_uses_injected_store_and_generator(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.sqlite'
            def connect():
                conn=sqlite3.connect(path)
                conn.row_factory=sqlite3.Row
                return conn
            with connect() as conn:
                conn.executescript('''CREATE TABLE entities(id INTEGER,type TEXT,name TEXT,status TEXT);
                    CREATE TABLE signals(signal_type TEXT,entity_id INTEGER,date TEXT,payload_json TEXT);
                    CREATE TABLE raw_documents(id INTEGER,title TEXT,published_at TEXT,source_type TEXT,markdown TEXT);
                    CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT);
                    CREATE TABLE enrichments(doc_id INTEGER,time_orientation TEXT,reference_period TEXT);
                    CREATE TABLE narratives(id INTEGER,topic TEXT,version INTEGER,superseded_at TEXT,created_at TEXT);''')
                now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                for ident,name,delta in [(1,'최근 생성',12),(2,'첫 주제',10),(3,'둘째 주제',8),(4,'셋째 주제',6)]:
                    conn.execute('INSERT INTO entities VALUES (?,\'theme\',?,NULL)',(ident,name))
                    conn.execute('INSERT INTO signals VALUES (\'theme_surge\',?,?,?)',(ident,now[:10],json.dumps({'share_delta_pp':delta,'is_new':True})))
                    for n in range(3):
                        doc=ident*10+n
                        conn.execute('INSERT INTO raw_documents VALUES (?,?,?,\'blog\',?)',(doc,'합성',now,'본문'))
                        conn.execute('INSERT INTO entity_links VALUES (?, ?, \'topic\')',(doc,ident))
                conn.execute('INSERT INTO narratives VALUES (1,\'최근 생성\',1,NULL,?)',(now,))
            generated=[]
            with patch('pipeline.narrative.get_connection',side_effect=AssertionError('unexpected default DB')), \
                 patch('pipeline.narrative._mt_boosted',return_value=set()), \
                 patch('pipeline.narrative._approved_new_topics',return_value=[]):
                result=compute_urgent_narratives(connection_factory=connect,
                    generate=lambda topic: generated.append(topic) or {'status':'fresh'},
                    record_candidate=lambda topic,status:None)
                with self.assertRaisesRegex(ValueError,'explicit generation'):
                    compute_urgent_narratives(connection_factory=connect)
            self.assertEqual(generated,['첫 주제','둘째 주제'])
            self.assertIn('쿨다운',result['skipped']['최근 생성'])
            self.assertEqual(result['results'],{'첫 주제':'fresh','둘째 주제':'fresh'})


if __name__ == '__main__':
    unittest.main()

"""Trusted collection tests use disposable databases and never fetch providers."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
import pyarrow.parquet as pq
from pipeline.market_analysis.snapshot import export_snapshot

path=Path(__file__).resolve().parents[2]/'scripts/collect_market_history.py'
spec=importlib.util.spec_from_file_location('market_history_collection',path)
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'source.sqlite'
        self.folder=self.root/'collection';self.published=self.root/'market_history.sqlite'
        with closing(sqlite3.connect(self.source)) as c:
            c.executescript('''CREATE TABLE stock_prices(stock_code TEXT,trade_date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,market_cap REAL,shares REAL,UNIQUE(stock_code,trade_date));
            CREATE TABLE companies(stock_code TEXT,corp_name TEXT,market TEXT);
            CREATE TABLE private_notes(text TEXT);
            INSERT INTO private_notes VALUES('untouched');
            INSERT INTO companies VALUES('000001','테스트','KOSPI');
            INSERT INTO stock_prices VALUES('000001','2026-09-17',100,105,95,102,1000,600000000000,6000000),('000001','2026-09-18',100,90,95,102,1000,700000000000,7000000);''')
            c.commit()
        self.before=self.source.read_bytes()

    def stage(self):
        collector.plan(self.source,self.folder)
        with closing(collector.stage_connection(self.folder)) as c:
            c.executemany('INSERT INTO prices VALUES(?,?,?,?,?,?,?)',[
                ('000001','2026-09-16',98,101,97,100,1200),
                ('000001','2026-09-17',104,110,100,108,1300),
                ('000001','2026-09-18',102,110,101,105,1500)])
            c.execute("UPDATE tasks SET status='collected',rows=3")
            collector.put_meta(c,'provider',{'name':'NAVER','fixture':True});c.commit()

    def test_plan_reaches_old_invalid_history(self):
        with closing(sqlite3.connect(self.source)) as c:
            c.execute("INSERT INTO stock_prices VALUES('000001','2021-01-04',0,1,0,1,100,NULL,NULL)");c.commit()
        collector.plan(self.source,self.folder)
        with closing(collector.stage_connection(self.folder)) as c:
            self.assertEqual(c.execute('SELECT start,end FROM tasks').fetchone(),('2021-01-04','2026-09-18'))

    def test_publish_leaves_entire_original_byte_identical(self):
        self.stage();collector.publish(self.folder,self.published)
        self.assertEqual(self.source.read_bytes(),self.before)
        with closing(collector.readonly(self.published)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM prices').fetchone()[0],3)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(self.published.stat().st_mode & 0o222,0)

    def test_export_uses_coherent_prices_and_original_cap(self):
        self.stage();collector.publish(self.folder,self.published)
        out=self.root/'snapshot';manifest=export_snapshot(self.source,out)
        rows=pq.read_table(out/'daily.parquet').to_pylist()
        self.assertEqual([r['close'] for r in rows],[100,108,105])
        self.assertIsNone(rows[0]['mktcap']);self.assertEqual(rows[-1]['mktcap'],700000000000)
        self.assertEqual(manifest['price_adjustment']['status'],'adjusted')
        self.assertEqual(manifest['quality']['000001']['source'],'NAVER')
        self.assertEqual(self.source.read_bytes(),self.before)

    def test_stale_history_does_not_mix_new_raw_price(self):
        self.stage();collector.publish(self.folder,self.published)
        with closing(sqlite3.connect(self.source)) as c:
            c.execute("INSERT INTO stock_prices VALUES('000001','2026-09-21',120,122,119,121,1000,NULL,NULL)");c.commit()
        manifest=export_snapshot(self.source,self.root/'snapshot')
        self.assertEqual(manifest['as_of'],'2026-09-18')
        self.assertEqual(manifest['source_latest_date'],'2026-09-21')
        self.assertTrue(any('추가 수집' in w for w in manifest['warnings']))

    def test_uncollected_symbols_stay_visible_with_unknown_provenance(self):
        self.stage()
        with closing(sqlite3.connect(self.source)) as c:
            c.execute("INSERT INTO stock_prices VALUES('000002','2026-09-18',10,11,9,10,100,NULL,NULL)");c.commit()
        collector.publish(self.folder,self.published)
        m=export_snapshot(self.source,self.root/'snapshot')
        self.assertEqual(m['symbols'],2);self.assertEqual(m['price_adjustment']['status'],'unknown')
        self.assertEqual(m['quality']['000002']['source'],'unknown')

    def test_invalid_stage_cannot_replace_good_published_history(self):
        self.stage();collector.publish(self.folder,self.published);before=self.published.read_bytes()
        with closing(collector.stage_connection(self.folder)) as c:
            c.execute("UPDATE prices SET low=0 WHERE date='2026-09-18'");c.commit()
        with self.assertRaisesRegex(ValueError,'Invalid staged'):collector.publish(self.folder,self.published)
        self.assertEqual(self.published.read_bytes(),before);self.assertEqual(self.source.read_bytes(),self.before)

    def test_source_overwrite_and_unfinished_collection_rejected(self):
        collector.plan(self.source,self.folder)
        with self.assertRaisesRegex(ValueError,'dedicated'):collector.publish(self.folder,self.source)
        with self.assertRaisesRegex(ValueError,'finish'):collector.publish(self.folder,self.published)

    def test_old_reader_keeps_consistent_snapshot_through_publication(self):
        self.stage();collector.publish(self.folder,self.published)
        with closing(collector.readonly(self.published)) as old:
            old.execute('BEGIN');self.assertEqual(old.execute('SELECT count(*) FROM prices').fetchone()[0],3)
            with closing(collector.stage_connection(self.folder)) as c:
                c.execute("INSERT INTO prices VALUES('000001','2026-09-15',95,99,94,98,500)");c.commit()
            collector.publish(self.folder,self.published)
            self.assertEqual(old.execute('SELECT count(*) FROM prices').fetchone()[0],3)
            with closing(collector.readonly(self.published)) as new:
                self.assertEqual(new.execute('SELECT count(*) FROM prices').fetchone()[0],4)

if __name__=='__main__':unittest.main()

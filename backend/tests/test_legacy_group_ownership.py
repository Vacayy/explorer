"""Legacy operator collections stay identical when member groups are added."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import kr_company_data as kr, world_reads as world, watch_rules as wr
from security.member_portfolio import initialize_ownership
from tests.test_watch_rules import BASE


class LegacyGroupOwnershipTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'fixture.sqlite'
        with self.db() as conn:
            conn.executescript(BASE+wr.SCHEMA+'''
                CREATE TABLE entities(id INTEGER PRIMARY KEY,type,name,aliases);
                INSERT INTO companies VALUES('legacy','Legacy','000001','KOSPI','IT'),
                    ('member','Member','000002','KOSPI','IT');
                INSERT INTO entities VALUES(1,'company','Legacy','000001'),(2,'company','Member','000002');
                INSERT INTO transcript_follow VALUES('OLDUS','Legacy US',NULL),('NEWUS','Member US',NULL);
                INSERT INTO stock_groups(id,name,kind) VALUES(1,'Legacy portfolio','portfolio'),(2,'Legacy watch','watch');
                INSERT INTO stock_group_members(group_id,stock_code) VALUES(1,'000001'),(2,'OLDUS');
                INSERT INTO watch_rules(group_id,strategy_id) VALUES(1,'high_5d'),(2,'high_5d');
                INSERT INTO stock_prices(stock_code,trade_date,open,high,low,close,volume,market_cap,shares)
                    VALUES('000001','2026-11-13',10,12,9,11,100,1000,10),('000002','2026-11-13',10,12,9,11,100,2000,10);
                INSERT INTO us_prices(stock_code,trade_date,open,high,low,close,volume)
                    VALUES('OLDUS','2026-11-13',10,12,9,11,100),('NEWUS','2026-11-13',10,12,9,11,100);
            ''')

    def connection(self):
        conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row
        return conn

    @contextmanager
    def db(self):
        conn=self.connection()
        try:
            with conn:yield conn
        finally:conn.close()

    def add_members(self):
        with self.db() as conn:
            initialize_ownership(conn)
            conn.executescript('''
                INSERT INTO stock_groups(id,name,kind,owner_id) VALUES
                    (3,'A','portfolio','member-a'),(4,'B','watch','member-b');
                INSERT INTO stock_group_members(group_id,stock_code) VALUES(3,'000002'),(3,'000001'),(4,'NEWUS'),(4,'000001');
                INSERT INTO watch_rules(group_id,strategy_id) VALUES(3,'high_5d'),(4,'high_5d');
            ''')

    def test_market_collection_and_world_personal_sets_preserve_legacy_results(self):
        with self.db() as conn:
            targets=kr.targets(conn,top_n=0)
            world_set=world._member_companies(conn)
        self.add_members()
        with self.db() as conn:
            self.assertEqual(kr.targets(conn,top_n=0),targets)
            self.assertEqual(world._member_companies(conn),world_set)
            self.assertEqual({s['stock_code'] for s in world_set},{'000001','OLDUS'})
            # Public market-cap collection remains market data, even if a member
            # also holds the stock. It must not become a personal priority tier.
            all_targets=kr.targets(conn,top_n=2)
            self.assertEqual(next(t['tier'] for t in all_targets if t['stock_code']=='000002'),'market_cap')

    def run_job(self):
        with patch.object(wr,'connect',self.connection),patch.object(wr,'record_run') as record, \
             patch('pipeline.us_data.fetch_prices',return_value=0) as fetch:
            total=wr.evaluate_all(force=True)
        return total,[c.args for c in fetch.call_args_list],record.call_args.args[:3]

    def test_job_prices_evaluations_and_summary_exclude_member_groups(self):
        baseline,fetches,record=self.run_job()
        with self.db() as conn:
            evaluations=[tuple(r) for r in conn.execute('SELECT group_id,stock_code,rule_id,as_of,status,value,reference,signal_date,reason FROM watch_evaluations ORDER BY group_id,stock_code')]
        self.add_members()
        total,new_fetches,new_record=self.run_job()
        self.assertEqual(total,baseline);self.assertEqual(new_fetches,fetches)
        self.assertEqual(fetches,[('OLDUS',)]);self.assertEqual(new_record,record)
        with self.db() as conn:
            self.assertEqual([tuple(r) for r in conn.execute('SELECT group_id,stock_code,rule_id,as_of,status,value,reference,signal_date,reason FROM watch_evaluations ORDER BY group_id,stock_code')],evaluations)
            self.assertEqual(conn.execute('SELECT count(*) FROM watch_evaluations WHERE group_id IN (3,4)').fetchone()[0],0)


if __name__=='__main__':unittest.main()

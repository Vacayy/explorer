import sqlite3,tempfile,unittest
from pathlib import Path
from security.public_tw_revenue import stored_revenue

class PublicTwRevenueTests(unittest.TestCase):
    def test_snapshot_reads_disclosures_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tw.sqlite'
            with sqlite3.connect(path) as c:
                c.execute('CREATE TABLE tw_monthly_revenue(code,ym,market,revenue,last_year,mom_pct,yoy_pct,note,fetched_at)')
                c.execute("INSERT INTO tw_monthly_revenue VALUES('2330','2026-10','sii',100,80,2,25,NULL,'2026-11-10')")
            before=path.read_bytes()
            result=stored_revenue(path=path)
            item=next(x for x in result['items'] if x['code']=='2330')
            self.assertEqual((result['as_of'],item['revenue'],item['yoy_pct']),('2026-10',100,25))
            self.assertEqual(path.read_bytes(),before)

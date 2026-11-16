import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_market_today as fixtures
from pipeline import market_today as mt
from security.public_market_today import public_market_today
from security.public_documents import DocumentUnavailable
from models.public_documents import PublishedDocument

class PublicMarketTodayTests(unittest.TestCase):
    setUp = fixtures.MarketTodayTests.setUp
    connect = fixtures.MarketTodayTests.connect

    def test_stored_topics_navigation_keep_body_but_remove_unreviewed_links(self):
        c=self.connect();mt.ensure_schema(c)
        topics=[dict(title='Stored topic',body='Stored market summary',tags=['market'],refs=['yes','no'],continuing=True,echo=2)]
        sources={key:dict(kind='telegram',publisher='private alias',title='private source title',url='https://private.test',
                         doc_id=ident,published_at='2026-11-13',echo=1) for key,ident in [('yes',1),('no',2)]}
        for day,slot in [('2026-11-12','1500'),('2026-11-13','0930'),('2026-11-13','1600')]:
            c.execute('INSERT INTO market_today(trade_date,slot,window_start,window_end,items_json,sources_json,doc_count,counts_json,links_at) VALUES(?,?,?,?,?,?,?,?,?)',
                      (day,slot,'start','end',json.dumps(topics),json.dumps(sources),2,'{"telegram":2,"news":0}','prepared'))
        c.commit();c.close()
        doc=PublishedDocument(id=1,title='Reviewed title',source_type='web',url='https://public.test',published_at='2026-11-13',content='body',content_kind='stored_text',attachments=[])
        def published(id,**kwargs):
            if id!=1:raise DocumentUnavailable()
            return SimpleNamespace(document=doc)
        before=self.path.read_bytes()
        with patch.object(mt,'ensure_schema',side_effect=AssertionError('DDL')), patch('pipeline.market_today_links.links_for_session',side_effect=AssertionError('private narrative')):
            result=public_market_today('2026-11-13',path=self.path,publications=SimpleNamespace(published=published)).model_dump()
            self.assertEqual(result['current']['slot'],'1600')
            self.assertEqual(result['prev_date'],'2026-11-12')
            self.assertEqual(result['current']['topics'][0]['body'],'Stored market summary')
            self.assertEqual(result['current']['topics'][0]['refs'],['yes'])
            self.assertEqual(result['current']['topics'][0]['sources'][0]['title'],'Reviewed title')
            self.assertFalse(result['current']['links_ready'])
            self.assertEqual(result['current']['topics'][0]['narratives'],[])
            self.assertNotIn('private',json.dumps(result))
            earlier=public_market_today('2026-11-13','0930',path=self.path,publications=SimpleNamespace(published=published))
            self.assertEqual(earlier.current.slot,'0930')
        self.assertEqual(self.path.read_bytes(),before)

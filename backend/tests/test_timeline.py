"""Feed contracts on an isolated corpus; never starts production lifespan or LLM."""
import sqlite3
import unittest
from pipeline.timeline import timeline, channels


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.executescript('''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT, url TEXT, published_at TEXT, fetched_at TEXT, markdown TEXT, media_json TEXT);
        CREATE TABLE enrichments(doc_id INTEGER, summary TEXT, model TEXT);
        CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT, type TEXT, aliases TEXT);
        CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT,confidence REAL);
        CREATE TABLE telegram_channels(channel_name TEXT,display_name TEXT,is_active INTEGER);
        CREATE TABLE blog_sources(url TEXT,blog_name TEXT,is_active INTEGER);
        CREATE TABLE youtube_channels(channel_id TEXT,title TEXT,is_active INTEGER);
        CREATE TABLE scrap_links(doc_id INTEGER,channel TEXT);
        CREATE TABLE entity_digests(id INTEGER,entity_id INTEGER,period TEXT,period_start TEXT,digest TEXT,doc_count INTEGER,created_at TEXT);
        CREATE TABLE source_digests(id INTEGER,kind TEXT,key TEXT,digest TEXT,doc_count INTEGER,created_at TEXT);
        CREATE TABLE transcripts(id INTEGER,raw_doc_id INTEGER,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT,digest TEXT,fetched_at TEXT);
        CREATE TABLE transcript_follow(ticker TEXT,company_name TEXT,active INTEGER);
        CREATE TABLE trade_stats(hs_code TEXT,period TEXT,fetched_at TEXT);
        CREATE TABLE trade_follow(hs_code TEXT,item_name TEXT,group_label TEXT,active INTEGER);
        INSERT INTO telegram_channels VALUES ('active','활성 채널',1),('muted','뮤트 채널',0);
        INSERT INTO youtube_channels VALUES ('yt','영상',1),('muted_yt','뮤트 영상',0);
        INSERT INTO blog_sources VALUES ('https://blog.naver.com/test','블로그',1),('https://blog.naver.com/muted','숨김',0);
        ''')

    def tearDown(self):
        self.c.close()

    def doc(self, ident, source='telegram', key='active', time='2026-09-09 10:00:00', url=''):
        self.c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident, source, f'{key}/{ident}', f'문서 {ident}', url, time, '2026-09-09 08:00:00', '본문', '[]'))

    def read(self, **kwargs):
        return timeline(self.c, until='2026-09-10T00:00:00Z', **kwargs)

    def test_only_active_sources_including_youtube_and_exact_blog(self):
        self.doc(1); self.doc(2,key='muted'); self.doc(3,key='unknown')
        self.doc(4,'youtube','yt'); self.doc(5,'youtube','muted_yt')
        self.doc(6,'blog',url='https://blog.naver.com/test/123')
        self.doc(7,'blog',url='https://blog.naver.com/muted/123')
        self.doc(8,'blog',url='https://blog.naver.com/testfake/123')
        self.assertEqual({i.id for i in self.read(scope='sources').items}, {'source:1','source:4','source:6'})

    def test_platform_filter_and_missing_summary_fallback(self):
        self.doc(1); self.doc(2,'youtube','yt')
        r=self.read(scope='sources',source='youtube')
        self.assertEqual([i.id for i in r.items],['source:2'])
        self.assertIsNone(r.items[0].document.summary)
        self.assertEqual(r.items[0].document.content,'본문')

    def test_source_attribution_prefers_exact_path_over_rss_domain(self):
        self.c.executescript("""
        INSERT INTO blog_sources VALUES ('https://example.com/a-very-long-news-feed.xml','RSS',1),
        ('https://example.com/author','작성자',1);
        """)
        self.doc(1,'blog',url='https://example.com/author/post')
        self.doc(2,'blog',url='https://example.com/other/post')
        docs={i.document.id:i.document for i in self.read().items}
        self.assertEqual(docs[1].channel,'작성자')
        self.assertEqual(docs[2].channel,'RSS')

    def test_blog_url_boundary_and_feed_domain_fallback(self):
        from pipeline.urls import url_belongs
        self.assertFalse(url_belongs('https://blog.naver.com/alice2/post','https://blog.naver.com/alice'))
        self.assertTrue(url_belongs('https://blog.naver.com/alice/post','https://blog.naver.com/alice/'))
        self.assertTrue(url_belongs('https://www.hankyung.com/article/1','https://rss.hankyung.com/feed/'))
        self.assertFalse(url_belongs('https://www.hankyung.com.fake/article/1','https://rss.hankyung.com/feed/'))

    def test_timezone_and_snapshot_pagination(self):
        self.doc(1,time='2026-09-09 10:00:00')
        self.doc(2,time='2026-09-09T18:00:00+09:00')  # 09:00 UTC, earlier than 1
        self.doc(3,time='2026-09-11T00:00:00Z')
        a=self.read(size=1); b=self.read(size=1,page=2)
        self.assertEqual(a.items[0].id,'source:1')
        self.assertEqual(b.items[0].id,'source:2')
        self.assertTrue(a.has_more); self.assertFalse(b.has_more)
        self.assertEqual(b.items[0].occurred_at,'2026-09-09T09:00:00+00:00')

    def test_ties_stable_and_no_duplicates_across_pages(self):
        for i in range(1,7):self.doc(i)
        ids=[i.id for p in range(1,4) for i in self.read(size=2,page=p).items]
        self.assertEqual(ids,[f'source:{i}' for i in range(6,0,-1)])

    def test_company_and_person_stored_summaries_only(self):
        self.c.executescript('''
        INSERT INTO entities VALUES (1,'SK하이닉스','company','000660'),(2,'MU','company','MU');
        INSERT INTO entity_digests VALUES (1,1,'1d','2026-09-08','메모리 요약',4,'2026-09-09 01:00:00'),
        (2,2,'1w','2026-09-07','주간 요약',7,'2026-09-09 02:00:00'),(3,1,'1m','2026-09-01','',0,'2026-09-09 03:00:00');
        INSERT INTO source_digests VALUES (1,'person','일론 머스크','인물 요약',30,'2026-09-09 04:00:00'),
        (2,'blog','블로그','소스 프로필',3,'2026-09-09 05:00:00');
        ''')
        r=self.read(scope='system')
        self.assertEqual([i.id for i in r.items],['person:1','company:2','company:1'])
        self.assertEqual(r.items[1].to,'/us/MU')
        self.assertEqual(r.items[2].to,'/analyze/000660/summary')
        self.assertEqual(r.items[0].evidence_count,30)
        self.assertEqual(len(self.read(scope='system',kind='person').items),1)

    def test_transcript_once_and_correct_detail(self):
        self.doc(1,'transcript','MU')
        self.c.executescript('''
        INSERT INTO transcript_follow VALUES ('MU','Micron',1),('NVDA','NVIDIA',0);
        INSERT INTO transcripts VALUES (1,1,'MU',2026,'Q3',NULL,'2026-09-09 10:00:00'),
        (2,1,'NVDA',2026,'Q3','요약','2026-09-09 11:00:00');
        ''')
        r=self.read()
        self.assertEqual([i.id for i in r.items],['transcript:1'])
        self.assertFalse(r.items[0].ai_generated)
        self.assertEqual(r.items[0].to,'/follow/transcripts?t=1')
        self.assertEqual(r.items[0].links[0].to,'/doc/1')

    def test_trade_latest_month_only_grouped_not_backfill_bump(self):
        self.c.executescript('''
        INSERT INTO trade_follow VALUES ('8542','반도체','IT',1),('8703','승용차','자동차',1),('27','연료','에너지',0);
        INSERT INTO trade_stats VALUES ('8542','2021-01','2026-09-09 23:00:00'),
        ('8542','2026-08','2026-09-09 10:00:00'),('8703','2026-08','2026-09-09 10:01:00'),
        ('27','2026-09','2026-09-09 12:00:00');
        ''')
        r=self.read(scope='system',kind='trade')
        self.assertEqual([i.id for i in r.items],['trade:2026-08'])
        self.assertIn('2개 품목',r.items[0].title)
        self.assertEqual(len(r.items[0].links),2)
        self.assertFalse(r.items[0].ai_generated)

    def test_read_only_empty_and_invalid_media(self):
        self.assertEqual(self.read().items,[])
        self.doc(1,time='')
        self.c.execute("UPDATE raw_documents SET media_json='invalid'")
        self.c.execute('PRAGMA query_only=ON')
        before=self.c.total_changes
        r=self.read()
        self.assertEqual(r.items[0].time_label,'수집')
        self.assertEqual(r.items[0].document.images,[])
        self.assertEqual(before,self.c.total_changes)

    def test_directory_counts_whole_corpus_and_empty_subscriptions(self):
        for i in range(1, 46): self.doc(i)
        self.doc(50, key='muted')
        self.doc(51, time='2026-09-11T00:00:00Z')
        directory = channels(self.c, until='2026-09-10T00:00:00Z')
        by_id = {i.id:i for i in directory.items}
        self.assertEqual(by_id['telegram:active'].count, 45)
        self.assertEqual(by_id['youtube:yt'].count, 0)
        self.assertNotIn('telegram:muted', by_id)
        self.assertEqual(directory.total, 45)
        self.assertEqual(by_id['telegram:active'].preview, '문서 9')  # stable lexical id tie-break
        self.assertEqual(len(self.read(channel='telegram:active',page=3).items),5)
        self.assertEqual(self.read(channel='telegram:unknown').items,[])

    def test_channel_filter_precedes_pagination_and_exact_blog_identity(self):
        for i in range(1, 30): self.doc(i)
        self.doc(100, 'youtube', 'yt', time='2026-09-08T00:00:00Z')
        self.doc(101, 'blog', url='https://blog.naver.com/test/123')
        self.doc(102, 'blog', url='https://blog.naver.com/testfake/123')
        self.assertEqual([i.id for i in self.read(channel='youtube:yt').items], ['source:100'])
        self.assertEqual([i.id for i in self.read(channel='blog:https://blog.naver.com/test').items], ['source:101'])

    def test_system_channels_group_by_target_not_display_name(self):
        self.c.executescript("""
        INSERT INTO entities VALUES (1,'같은 이름','company','A'),(2,'같은 이름','company','B');
        INSERT INTO entity_digests VALUES (1,1,'1d','2026-09-08','하루',4,'2026-09-09 01:00:00'),
        (2,1,'1w','2026-09-07','주간',7,'2026-09-09 02:00:00'),
        (3,2,'1d','2026-09-08','다른 기업',4,'2026-09-09 01:00:00');
        INSERT INTO source_digests VALUES (1,'person','인물:키','인물 요약',2,'2026-09-09 04:00:00');
        """)
        self.assertEqual([i.id for i in self.read(channel='company:1').items],['company:2','company:1'])
        self.assertEqual([i.id for i in self.read(channel='person:인물:키').items],['person:1'])
        before=self.c.total_changes
        self.c.execute('PRAGMA query_only=ON')
        by_id={i.id:i for i in channels(self.c,until='2026-09-10T00:00:00Z').items}
        self.assertEqual(by_id['company:1'].count,2)
        self.assertEqual(by_id['company:2'].count,1)
        self.assertEqual(before,self.c.total_changes)


if __name__ == '__main__':unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from pipeline.connectors import youtube

CID = 'UCKTMvIu9a4VGSrpWy-8bUrQ'
TITLE = '내일은 투자왕 - 김단테'
RSS = f'''<feed xmlns="http://www.w3.org/2005/Atom"><title>{TITLE}</title><link rel="alternate" href="https://www.youtube.com/channel/{CID}"/></feed>'''.encode()

class ChannelNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'names.db'
        conn = self.connect()
        conn.executescript('CREATE TABLE youtube_channels(channel_id TEXT PRIMARY KEY,title TEXT,is_active INT,collect_enabled INT); CREATE TABLE raw_documents(source_id TEXT,source_type TEXT);')
        conn.execute('INSERT INTO youtube_channels VALUES(?,?,1,1)', (CID, CID));conn.commit();conn.close()
        p=patch.object(youtube,'get_connection',side_effect=self.connect);p.start();self.addCleanup(p.stop)
    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def title(self):
        c=self.connect(); value=c.execute('SELECT title FROM youtube_channels').fetchone()[0];c.close();return value
    def test_discovery_repairs_name_even_without_new_videos(self):
        with patch.object(youtube.requests,'get',return_value=Mock(content=RSS)):
            self.assertEqual(youtube.YouTubeConnector().discover(), [])
        self.assertEqual(self.title(), TITLE)
    def test_valid_existing_name_is_not_overwritten(self):
        c=self.connect();c.execute('UPDATE youtube_channels SET title=?',('내가 지정한 이름',));c.commit();c.close()
        with patch.object(youtube.requests,'get',return_value=Mock(content=RSS)):
            youtube.YouTubeConnector().discover()
        self.assertEqual(self.title(),'내가 지정한 이름')
    def test_unrelated_or_error_feed_does_not_replace_name(self):
        for content in [b'<html><title>Error</title></html>', RSS.replace(CID.encode(),b'UCdifferent_channel')]:
            with patch.object(youtube.requests,'get',return_value=Mock(content=content)):
                youtube.YouTubeConnector().discover()
            self.assertEqual(self.title(),CID)
    def test_registration_title_lookup_validates_and_repairs_before_caching(self):
        with patch('services.cache_service.is_cached',return_value=False), patch('services.cache_service.set_cache') as cache, patch.object(youtube.requests,'get',return_value=Mock(content=RSS)):
            self.assertEqual(youtube._channel_title(CID),TITLE)
            cache.assert_called_once()
        self.assertEqual(self.title(),TITLE)
    def test_failed_title_lookup_does_not_cache_placeholder(self):
        with patch('services.cache_service.is_cached',return_value=False), patch('services.cache_service.set_cache') as cache, patch.object(youtube.requests,'get',side_effect=RuntimeError('offline')):
            self.assertEqual(youtube._channel_title(CID),CID)
            cache.assert_not_called()
        self.assertEqual(self.title(),CID)

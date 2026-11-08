"""유튜브 RSS가 죽어도 채널 '동영상' 페이지로 새 영상을 찾는다 (2026-11 RSS 전 채널 404)."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline.connectors import youtube

CID = 'UCpqD9_OJNtF6suPpi6mOQCQ'


def page(*items):
    data = {"contents": {"tabs": [{"richGridRenderer": {"contents": list(items)}}]}}
    return f'<script>var ytInitialData = {json.dumps(data)};</script>'


def lockup(vid, title, kind='LOCKUP_CONTENT_TYPE_VIDEO'):
    return {"richItemRenderer": {"content": {"lockupViewModel": {
        "contentId": vid, "contentType": kind,
        "metadata": {"lockupMetadataViewModel": {"title": {"content": title}}}}}}}


def renderer(vid, title):
    return {"richItemRenderer": {"content": {"videoRenderer": {"videoId": vid, "title": {"runs": [{"text": title}]}}}}}


class PageParseTests(unittest.TestCase):
    def test_reads_new_and_old_layouts_in_order_without_duplicates(self):
        html = page(lockup('G-nU0m4athY', '새 영상'), renderer('aWARtvNi4GQ', '옛 형식'),
                    lockup('G-nU0m4athY', '중복'), lockup('PLxxxxxxxxx', '재생목록', 'LOCKUP_CONTENT_TYPE_PLAYLIST'))
        self.assertEqual([v['video_id'] for v in youtube._page_videos(html)], ['G-nU0m4athY', 'aWARtvNi4GQ'])

    def test_page_without_initial_data_is_empty(self):
        self.assertEqual(youtube._page_videos('<html>consent</html>'), [])


class DiscoverFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'yt.db'
        c = self.connect()
        c.executescript('CREATE TABLE youtube_channels(channel_id TEXT PRIMARY KEY,title TEXT,is_active INT,collect_enabled INT);'
                        'CREATE TABLE raw_documents(source_id TEXT,source_type TEXT);')
        c.execute('INSERT INTO youtube_channels VALUES(?,?,1,1)', (CID, '월가아재의 과학적 투자'))
        c.execute("INSERT INTO raw_documents VALUES(?, 'youtube')", (f'{CID}/aWARtvNi4GQ',))
        c.commit(); c.close()
        p = patch.object(youtube, 'get_connection', side_effect=self.connect); p.start(); self.addCleanup(p.stop)

    def connect(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row; return c

    def fake_get(self, url, **_):
        if 'feeds/videos.xml' in url:
            return Mock(status_code=404, content=b'<html><title>Error 404</title></html>')
        return Mock(status_code=200, text=page(lockup('G-nU0m4athY', '번역됐을 수 있는 제목'), lockup('aWARtvNi4GQ', '이미 있음')))

    def test_rss_404_falls_back_to_channel_page_and_skips_seen(self):
        with patch.object(youtube.requests, 'get', side_effect=self.fake_get):
            refs = youtube.YouTubeConnector().discover()
        self.assertEqual([r.key for r in refs], ['G-nU0m4athY'])
        # 제목·게시 시각은 비워 fetch가 oEmbed·시청 페이지에서 원본을 읽게 한다
        self.assertEqual(refs[0].meta['title'], '')
        self.assertEqual(refs[0].meta['published'], '')
        self.assertEqual(refs[0].meta['channel_id'], CID)


if __name__ == '__main__':
    unittest.main()

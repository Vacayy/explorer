import unittest
from unittest.mock import patch

from pipeline.base import SourceRef
from pipeline.connectors import blog


class BlogStagingTest(unittest.TestCase):
    def test_listing_is_saved_before_individual_full_text_fetch(self):
        posts = [{'url': 'https://blog.naver.com/test/1', 'title': 'one', 'content': 'excerpt'},
                 {'url': 'https://blog.naver.com/test/2', 'title': 'two', 'content': 'excerpt'}]
        connector = blog.BlogConnector()
        with patch.object(blog, 'detect_platform_and_feed_url', return_value=('naver', 'feed')), \
             patch.object(blog, 'scrape_rss', return_value=(posts, 'blog')), \
             patch('services.blog_service.fetch_full_content', return_value='longer full text') as full:
            refs = connector.discover_posts(SourceRef('feed'))
            self.assertEqual(len(refs), 2)
            full.assert_not_called()
            doc = connector.fetch_post(refs[0])
            self.assertEqual(doc.raw_content, 'longer full text')
            self.assertEqual(full.call_count, 1)

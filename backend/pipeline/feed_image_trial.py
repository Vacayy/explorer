"""Stage one real image interpretation without modifying the published document."""
import json

from bs4 import BeautifulSoup

from pipeline import image_reading
from pipeline.base import RawDoc


def stage_one(queue, before_attempt):
    rows = queue.conn.execute("SELECT seq,payload FROM pending WHERE defer_reason='analysis' "
                              "AND source_type='blog' ORDER BY seq LIMIT 20").fetchall()
    for seq, payload in rows:
        doc = RawDoc(**json.loads(payload))
        if doc.kind != 'html':
            continue
        soup = BeautifulSoup(doc.raw_content or '', 'html.parser')
        for tag in soup.find_all('img'):
            ref = image_reading.blog_image_ref(tag)
            if not ref:
                continue
            key, url = ref
            if queue.conn.execute('SELECT 1 FROM staged_image_results WHERE image_key=?', (key,)).fetchone():
                continue
            queue.begin_image(seq, key)
            before_attempt()  # consume the one-shot marker before network or model execution
            loaded = image_reading._load({'key': key, 'url': url, 'referer': doc.url})
            if loaded is None:
                queue.finish_image(key, None)
                return {'image_staged': 1, 'image_filtered': 1, 'image_calendar': 0, 'image_valid': 0}
            result = image_reading._call(*loaded, context=doc.raw_content, source='블로그·뉴스 글',
                                         published_at=doc.published_at)
            queue.finish_image(key, result)
            valid = result.get('kind') in {'calendar', 'chart', 'table', 'text', 'diagram', 'photo', 'other'}
            return {'image_staged': 1, 'image_filtered': 0, 'image_calendar': int(result.get('kind') == 'calendar'),
                    'image_valid': int(valid)}
    return {'image_staged': 0, 'image_filtered': 0, 'image_calendar': 0, 'image_valid': 0}

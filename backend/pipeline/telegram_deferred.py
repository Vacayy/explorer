"""Stage Telegram page snapshots while deferring missing AI-dependent history."""
import hashlib
import json

from database import get_connection
from pipeline import image_reading
from pipeline.base import SourceRef


class NeedsAnalysis(Exception):
    """Keep the original snapshot pending until grouping/image analysis is available."""


def page_reference(channel, messages):
    if not channel or not messages or any(not m.get('message_id') for m in messages):
        raise ValueError('A channel and identified messages are required')
    identity = json.dumps([channel, messages], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return SourceRef(key=hashlib.sha256(identity.encode()).hexdigest(),
                     meta={'channel': channel, 'messages': messages})


class ExistingMarks:
    def get(self, channel, msg_id):
        conn = get_connection()
        try:
            return conn.execute('SELECT joins_prev FROM telegram_group_marks WHERE channel=? AND msg_id=?',
                                (channel, msg_id)).fetchone()
        finally:
            conn.close()

    def put(self, *args):
        raise NeedsAnalysis('New grouping decisions require analysis')


def no_new_group_decision(*args):
    raise NeedsAnalysis('New grouping decisions require analysis')


def cached_images(items, **kwargs):
    if not items:
        return {}
    keys = [item['key'] for item in items[:image_reading.MAX_PER_DOC]]
    conn = get_connection()
    try:
        rows = image_reading._rows(conn, keys)
        if any(image_reading._needs(rows.get(key)) for key in keys):
            raise NeedsAnalysis('New image interpretation requires analysis')
        return {key: image_reading.format_note(rows.get(key)) for key in keys}
    finally:
        conn.close()

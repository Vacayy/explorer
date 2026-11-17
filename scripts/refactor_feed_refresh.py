"""Refresh isolated feed work from the idle collector copy, keeping its separate queue."""
import sqlite3

from pipeline.feed_backlog import FeedBacklog


def refresh(source_path, target_path, queue_path):
    queue = FeedBacklog(queue_path)
    try:
        if queue.intent():
            raise ValueError('Feed publication needs reconciliation before refresh')
        source = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
        target = sqlite3.connect(target_path)
        try:
            for conn in (source, target):
                if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('A work copy failed integrity check')
                for name, table in (('document_floor', 'raw_documents'), ('entity_floor', 'entities'),
                                    ('keyword_floor', 'entity_keywords'), ('relation_floor', 'entity_relations')):
                    floor = conn.execute('SELECT value FROM candidate_publish_floor WHERE name=?', (name,)).fetchone()
                    maximum = conn.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0]
                    if floor is None or floor[0] != maximum:
                        raise ValueError('A work copy contains unpublished data')
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Refreshed feed work failed integrity check')
        finally:
            target.close()
            source.close()
    finally:
        queue.close()


if __name__ == '__main__':
    refresh('/target/work.db', '/feed/work.db', '/feed/feed-backlog.sqlite')
    print('feed work refreshed and verified')

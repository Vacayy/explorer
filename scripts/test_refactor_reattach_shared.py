import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import refactor_reattach_shared as reattach

SCHEMA = '''
CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE enrichments(id INTEGER PRIMARY KEY, doc_id INTEGER);
CREATE TABLE entity_links(id INTEGER PRIMARY KEY, doc_id INTEGER, entity_id INTEGER);
CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY, entity_id INTEGER);
CREATE TABLE entity_relations(id INTEGER PRIMARY KEY, src_id INTEGER, dst_id INTEGER, source_doc_id INTEGER);
CREATE TABLE telegram_group_marks(channel TEXT, msg_id INTEGER, joins_prev INTEGER, PRIMARY KEY(channel, msg_id));
CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY, value INTEGER);
CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, close REAL);
'''


def work(path, docs, entities, prices):
    db = sqlite3.connect(path, isolation_level=None)
    db.executescript(SCHEMA)
    db.executemany('INSERT INTO raw_documents VALUES (?, ?)', [(i, f'd{i}') for i in docs])
    db.executemany('INSERT INTO enrichments VALUES (?, ?)', [(i, i) for i in docs])
    db.executemany('INSERT INTO entities VALUES (?, ?)', [(i, f'e{i}') for i in entities])
    db.executemany('INSERT INTO stock_prices VALUES (?, ?, ?)', prices)
    db.executemany('INSERT INTO candidate_publish_floor VALUES (?, ?)',
                   [('document_floor', max(docs)), ('entity_floor', max(entities)), ('keyword_floor', 0), ('relation_floor', 0)])
    return db


class ReattachTest(unittest.TestCase):
    def test_feed_rows_and_published_tables_come_over_in_one_transaction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared = work(root / 'shared.db', [1, 2], [10], [('005930', '2026-11-20', 100.0)])
            feed = work(root / 'feed.db', [1, 2, 3, 4], [10, 11], [('005930', '2026-11-20', 100.0)])
            feed.execute("INSERT INTO telegram_group_marks VALUES ('c', 1, 1)")
            projection = work(root / 'projection.db', [1, 2, 3, 4], [10, 11],
                              [('005930', '2026-11-20', 100.0), ('005930', '2026-11-23', 101.0)])
            projection.close()
            shared.execute('ATTACH DATABASE ? AS projection', (str(root / 'projection.db'),))
            shared.execute('BEGIN IMMEDIATE')
            appended = reattach.append_feed(feed, shared)
            counts = reattach.realign(shared, ['stock_prices'])
            shared.execute('COMMIT')
            self.assertEqual((appended['raw_documents'], appended['entities'], appended['telegram_group_marks']), (2, 1, 1))
            self.assertEqual(counts, {'stock_prices': 2})
            self.assertEqual(dict(shared.execute('SELECT name, value FROM candidate_publish_floor'))['document_floor'], 4)
            self.assertEqual(shared.execute("SELECT close FROM stock_prices WHERE trade_date='2026-11-23'").fetchone()[0], 101.0)

    def test_a_row_that_differs_below_the_floor_refuses(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared = work(root / 'shared.db', [1, 2], [10], [])
            feed = work(root / 'feed.db', [1, 2, 3], [10], [])
            feed.execute("UPDATE raw_documents SET title='changed' WHERE id=2")
            shared.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(ValueError, 'differ below the shared floor'):
                reattach.append_feed(feed, shared)
            shared.execute('ROLLBACK')
            self.assertEqual(shared.execute('SELECT count(*) FROM raw_documents').fetchone()[0], 2)

    def test_unpublished_rows_in_either_file_refuse(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared = work(root / 'shared.db', [1, 2], [10], [])
            feed = work(root / 'feed.db', [1, 2, 3], [10], [])
            feed.execute("UPDATE candidate_publish_floor SET value=2 WHERE name='document_floor'")  # doc 3 unpublished
            with self.assertRaisesRegex(ValueError, 'unpublished rows in the feed file'):
                reattach.append_feed(feed, shared)


if __name__ == '__main__':
    unittest.main()

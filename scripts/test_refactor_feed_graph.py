"""PG's graph rows above the collector file's floors appended before a feed run (refactor_feed_graph.catch_up)."""
import sqlite3
import unittest

import refactor_feed_graph as graph


class _PG:
    def __init__(self, rows, documents=0):
        self.rows, self.documents = rows, documents

    def execute(self, sql, args):
        if "'raw_documents'" in sql:
            return _One(self.documents)
        table, floor = args
        return [(row,) for row in self.rows.get(table, []) if row['id'] > floor]


class _One:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


def _work(floors=(10, 5, 20, 100), extra=()):
    work = sqlite3.connect(':memory:', isolation_level=None)
    work.executescript('''
        CREATE TABLE entities (id INTEGER PRIMARY KEY, type TEXT, name TEXT, UNIQUE(type, name));
        CREATE TABLE entity_keywords (id INTEGER PRIMARY KEY, entity_id INT, keyword TEXT);
        CREATE TABLE entity_relations (id INTEGER PRIMARY KEY, src_id INT, dst_id INT, rel_type TEXT);
        CREATE TABLE candidate_publish_floor (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
        INSERT INTO entities VALUES (10, 'company', 'A');
        INSERT INTO entity_keywords VALUES (5, 10, 'a');
        INSERT INTO entity_relations VALUES (20, 10, 10, 'X');''')
    for sql in extra:
        work.execute(sql)
    work.executemany('INSERT INTO candidate_publish_floor VALUES (?,?)',
                     zip(('entity_floor', 'keyword_floor', 'relation_floor', 'document_floor'), floors))
    return work


THEMES = {'entities': [{'id': 11, 'type': 'theme', 'name': 'T1'}, {'id': 12, 'type': 'sector', 'name': 'S'}],
          'entity_relations': [{'id': 21, 'src_id': 11, 'dst_id': 12, 'rel_type': 'CAUSES'}]}


class CatchUpTest(unittest.TestCase):
    def test_pg_graph_rows_appended_and_floors_moved(self):
        work = _work()
        self.assertEqual(graph.catch_up(_PG(THEMES), work), {'entities': 2, 'entity_keywords': 0, 'entity_relations': 1})
        self.assertEqual(work.execute('SELECT name FROM entities WHERE id=12').fetchone(), ('S',))
        floors = dict(work.execute('SELECT * FROM candidate_publish_floor'))
        self.assertEqual((floors['entity_floor'], floors['relation_floor']), (12, 21))
        # the next entity the file creates gets an ID PG does not have
        work.execute("INSERT INTO entities (type, name) VALUES ('company', 'TJX')")
        self.assertEqual(work.execute("SELECT id FROM entities WHERE name='TJX'").fetchone(), (13,))
        self.assertEqual(graph.catch_up(_PG(THEMES), _work((12, 5, 21, 100), extra=(
            "INSERT INTO entities VALUES (11,'theme','T1')", "INSERT INTO entities VALUES (12,'sector','S')",
            'INSERT INTO entity_relations VALUES (21,11,12,"CAUSES")'))),
            {'entities': 0, 'entity_keywords': 0, 'entity_relations': 0})  # repeat: nothing more

    def test_refused_without_change(self):
        cases = {
            'unpublished': (_work(extra=("INSERT INTO entities VALUES (11,'company','TJX')",)), _PG(THEMES)),
            'documents': (_work(), _PG(THEMES, documents=3)),
            'unique': (_work(extra=("UPDATE entities SET type='theme', name='T1' WHERE id=10",)), _PG(THEMES)),
            'endpoint': (_work(), _PG({'entity_relations': [{'id': 21, 'src_id': 10, 'dst_id': 99, 'rel_type': 'X'}]})),
            'columns': (_work(), _PG({'entities': [{'id': 11, 'type': 't', 'name': 'n', 'unknown': 1}]})),
        }
        for name, (work, pg) in cases.items():
            before = (work.execute('SELECT count(*) FROM entities').fetchone(), list(work.execute('SELECT * FROM candidate_publish_floor')))
            with self.subTest(name), self.assertRaises(ValueError):
                graph.catch_up(pg, work)
            self.assertEqual(before, (work.execute('SELECT count(*) FROM entities').fetchone(),
                                      list(work.execute('SELECT * FROM candidate_publish_floor'))))


if __name__ == '__main__':
    unittest.main()

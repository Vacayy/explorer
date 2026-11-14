"""문서 검색 결과 묶음 — 소스별 건수·자주 같이 나온 종목·테마 (ia-redesign §4.15). 격리 DB."""
import sqlite3
import unittest

from routers.spine_feed import _search_facets


class SearchFacetTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.executescript('''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT);
        CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT, aliases TEXT);
        CREATE TABLE entity_links(doc_id INTEGER, entity_id INTEGER, link_type TEXT);
        INSERT INTO raw_documents VALUES (1,'telegram'),(2,'telegram'),(3,'blog'),(4,'news');
        INSERT INTO entities VALUES (10,'SK하이닉스','000660'),(11,'반도체',NULL),(12,'홍길동',NULL);
        INSERT INTO entity_links VALUES (1,10,'stock'),(2,10,'stock'),(3,10,'stock'),(1,11,'industry'),(2,12,'person');
        ''')

    def test_counts_sources_and_cooccurring_entities_over_all_results(self):
        rows = self.c.execute('SELECT id, source_type FROM raw_documents WHERE id IN (1,2,3)').fetchall()
        f = _search_facets(self.c, rows)
        self.assertEqual(f.sources, {'telegram': 2, 'blog': 1})
        self.assertEqual([(e.name, e.count, e.aliases) for e in f.entities], [('SK하이닉스', 3, '000660'), ('반도체', 1, None)])

    def test_people_are_not_facets_and_empty_results_are_empty(self):
        f = _search_facets(self.c, [])
        self.assertEqual((f.sources, f.entities), ({}, []))


if __name__ == '__main__':
    unittest.main()

"""Same-source merge plan (pipeline.postgres_id_remap.merge_plan): entity keys first, then relation and alias keys
compared through the entity mapping (architect #3 6944207494)."""
import sqlite3
import unittest

from pipeline import postgres_id_remap as remap

BAND = 100_000_000


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Candidate:
    """Stands in for the PG connection: legacy_snapshot_rows of the candidate's banded rows."""
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, params):
        table, band = params
        return _Rows([(row,) for t, row in self.rows if t == table and row['id'] >= band])


def collector():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT);
        CREATE TABLE entities (id INTEGER PRIMARY KEY, type TEXT, name TEXT, UNIQUE(type, name));
        CREATE TABLE entity_keywords (id INTEGER PRIMARY KEY, entity_id INTEGER, keyword TEXT, UNIQUE(entity_id, keyword));
        CREATE TABLE entity_relations (id INTEGER PRIMARY KEY, src_id INTEGER, dst_id INTEGER, rel_type TEXT, valid_from TEXT,
                                       UNIQUE(src_id, dst_id, rel_type, valid_from));
        INSERT INTO entities VALUES (10, 'theme', 'A'), (24793, 'theme', 'Same');
        INSERT INTO entity_relations VALUES (19604, 10, 24793, 'drives', NULL);
        INSERT INTO entity_keywords VALUES (7, 24793, 'alias');
        INSERT INTO raw_documents VALUES (29452, 'web', 'u1');
    ''')
    return db


class MergePlan(unittest.TestCase):
    def test_entity_then_relation_and_alias_through_the_mapping(self):
        candidate = _Candidate([
            ('entities', {'id': BAND + 24793, 'type': 'theme', 'name': 'Same'}),
            ('entities', {'id': BAND + 24794, 'type': 'theme', 'name': 'Only the candidate'}),
            # Its key matches the MacBook's relation only once the candidate entity maps to 24793.
            ('entity_relations', {'id': BAND + 22681, 'src_id': 10, 'dst_id': BAND + 24793, 'rel_type': 'drives',
                                  'valid_from': None}),
            ('entity_relations', {'id': BAND + 22682, 'src_id': 10, 'dst_id': BAND + 24794, 'rel_type': 'drives',
                                  'valid_from': None}),
            ('entity_keywords', {'id': BAND + 2585, 'entity_id': BAND + 24793, 'keyword': 'alias'}),
            ('raw_documents', {'id': BAND + 29453, 'source_type': 'web', 'source_id': 'u1'}),
            ('raw_documents', {'id': BAND + 29454, 'source_type': 'web', 'source_id': 'u2'})])
        pairs = remap.merge_plan(candidate, collector())
        self.assertEqual(sorted(pairs), sorted([
            ('entity', BAND + 24793, 24793), ('relation', BAND + 22681, 19604), ('keyword', BAND + 2585, 7),
            ('document', BAND + 29453, 29452)]))

    def test_no_shared_key_no_pair(self):
        candidate = _Candidate([('entities', {'id': BAND + 1, 'type': 'event', 'name': 'Same'})])  # other type
        self.assertEqual(remap.merge_plan(candidate, collector()), [])


if __name__ == '__main__':
    unittest.main()

import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import database
from pipeline import narrative,world_reads
from security import public_narratives as public
from tests.test_world_reads import SEED

class PublicNarrativeTests(unittest.TestCase):
    def test_stored_changes_body_versions_and_graph_exclude_private_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'narratives.sqlite'
            with patch.object(database,'DB_PATH',path):database.init_db()
            with sqlite3.connect(path) as c:
                c.row_factory=sqlite3.Row;c.executescript(SEED)
                c.execute("UPDATE entity_relations SET feedback_note='private-note-canary', obs_confirmed_at='private-obs-canary'")
                c.execute("UPDATE questions SET text='private-question-canary'")
                c.commit()
                expected=world_reads.narrative_changes(c)
            before=path.read_bytes()
            with patch.object(narrative,'_call',side_effect=AssertionError('generation')):
                result=public.changes(path=path)
                for field in ['topic','narrative_id','version','title','change_summary','added_count','removed_count']:
                    self.assertEqual(result['items'][0][field],expected['items'][0][field])
                self.assertEqual(public.stored_body('메모리',path=path)['narrative'],'v2')
                self.assertEqual(public.stored_body(version_id=10,path=path)['narrative'],'v1')
                self.assertEqual(len(public.versions('메모리',path=path)),2)
                self.assertEqual(public.stored_body(version_id=20,path=path)['status'],'not_found')
                self.assertEqual(public.graph(20,path=path),{'nodes':[],'edges':[]})
                self.assertEqual(public.diff(20,path=path)['status'],'not_found')
                graph=public.graph(11,path=path)
                self.assertEqual(len(graph['edges']),3)
                self.assertNotIn('canary',json.dumps(graph))
                self.assertTrue(all(e['source_status']=='unverified' for e in graph['edges']))
                self.assertEqual(public.diff(11,path=path)['status'],'ok')
                related=public.related(11,path=path)
                self.assertIn(related['status'], ('ok', 'empty'))
                self.assertNotIn('canary',json.dumps(related))
                self.assertEqual(public.related(20,path=path), {'status':'empty','related':[]})
            conn=public.connection(path)
            try:
                for sql in ['SELECT text FROM questions','SELECT feedback_note FROM entity_relations','DELETE FROM narratives','CREATE TABLE injected(x)']:
                    with self.assertRaises(sqlite3.DatabaseError):conn.execute(sql)
            finally:conn.close()
            self.assertEqual(before,path.read_bytes())

if __name__=='__main__':unittest.main()

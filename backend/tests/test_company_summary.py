import sqlite3
import unittest
from unittest.mock import patch
from pipeline.company_summary import summarize_company_evidence, MAX_DOCS, MAX_CHARS

class CompanySummaryTests(unittest.TestCase):
    def run_summary(self, generated, items=None):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE raw_documents(id INTEGER, markdown TEXT)')
        conn.execute('INSERT INTO raw_documents VALUES(1,?)', ('x'*(MAX_CHARS+20),))
        conn.commit()
        items=items if items is not None else [dict(id='doc:1',doc_id=1,title='컨콜',publisher='회사',published_at='2026-06-12',status='after',time_precision='date',source_type='transcript'),dict(id='disclosure:1',doc_id=None,title='공시 제목',publisher='DART',published_at='2026-06-11',status='within',time_precision='date',source_type='disclosure')]
        with patch('pipeline.company_summary.get_connection',return_value=conn),patch('pipeline.company_summary.company_evidence',return_value={'items':items,'total':45}) as selection,patch('pipeline.company_summary._call_json',return_value=generated) as llm:
            result=summarize_company_evidence('005930',start='2026-06-01',end='2026-06-12',source='transcript',q='실적',after=True)
            selection.assert_called_once_with(conn,'005930',page=1,size=MAX_DOCS,start='2026-06-01',end='2026-06-12',source='transcript',q='실적',after=True)
            with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
            return result,llm
    def test_bounds_scope_sources_and_truncation(self):
        r,llm=self.run_summary({'points':[{'text':'확인된 내용','sources':[1,2,999,1]}]})
        self.assertEqual(r['points'][0]['sources'],[1,2]);self.assertEqual(r['used_count'],2)
        self.assertEqual(r['total'],45);self.assertEqual(r['title_only_count'],1);self.assertEqual(r['truncated_count'],1)
        prompt=llm.call_args.args[0];self.assertIn('"status": "after"',prompt);self.assertIn('"title_only": true',prompt)
        self.assertNotIn('x'*(MAX_CHARS+1),prompt)
    def test_unknown_citations_do_not_render_as_evidence(self):
        with self.assertRaises(ValueError):self.run_summary({'points':[{'text':'근거 없는 주장','sources':[999,True]}]})
    def test_empty_selection_does_not_call_llm(self):
        r,llm=self.run_summary({},items=[]);llm.assert_not_called();self.assertEqual(r['points'],[])
    def test_malformed_points_are_rejected(self):
        with self.assertRaises(ValueError):self.run_summary({'points':['bad',{'text':'bad','sources':'1'}]})

if __name__=='__main__':unittest.main()

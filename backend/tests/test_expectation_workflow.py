"""Isolated workflow tests: never start production lifespan or invoke a live model."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import expectation_evidence as evidence, expectation_store as store, expectation_workflow as flow
from routers.experiment_expectations import router

BASE = '/api/experiments/expectations'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.tmp.name) / 'corpus.sqlite'
        self.experiment = Path(self.tmp.name) / 'experiment.sqlite'
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute('''CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT,
                         source_id TEXT,title TEXT,url TEXT,published_at TEXT,fetched_at TEXT,
                         raw_content TEXT,markdown TEXT,digest_status TEXT)''')
            for i in range(1,8):
                body=f'안녕하세요. 연구자입니다. 2027년 DRAM 계약가 상승률을 {i*10}%로 전망합니다.'
                c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (i,'telegram','channel',f'DRAM 전망 {i}','https://example.test/report',
                           f'2026-08-{i:02}T10:00:00+09:00','2026-09-01T00:00:00Z',body,body,None))
            body='HBM 원본 자막 3,000자 → opus 정리본'
            c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (8,'youtube','channel','정리본',None,None,None,body,body,'ok'))
        self.original = self.corpus.read_bytes()
        for obj,name,value in [(evidence,'DB_PATH',self.corpus),(store,'EXPERIMENT_DB',self.experiment)]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.submit=patch.object(flow.POOL,'submit').start()
        self.addCleanup(patch.stopall)
        app=FastAPI();app.include_router(router)
        self.client=TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.tmp.cleanup)

    def fields(self,doc_id=1,**changes):
        data=dict(speaker='연구자',attribution='direct',speaker_quote='안녕하세요. 연구자입니다.',
                  product='dram',target='메모리 산업',metric='price',axis='growth',horizon='2027',
                  basis='범용 DRAM 계약가',direction='up',value=doc_id*10,unit='% YoY',
                  quote=f'2027년 DRAM 계약가 상승률을 {doc_id*10}%로 전망합니다.',claim='DRAM 가격 상승 전망',conditions='')
        return data|changes

    def manual(self,doc_id=1,**changes):
        doc=evidence.get_document(doc_id)
        response=self.client.post(BASE+'/statements',json=self.fields(doc_id,**changes)|dict(doc_id=doc_id,text_sha256=doc.text_sha256))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def review(self,s,status='approved',**changes):
        return self.client.post(BASE+f"/statements/{s['id']}/review",json=s['fields']|dict(expected_revision=s['revision'],status=status,note='')|changes)

    def approved(self,doc_id=1,**changes):
        response=self.review(self.manual(doc_id,**changes))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def comparison(self,s):
        return self.client.get(BASE+f"/statements/{s['id']}/comparison").json()

    def queued(self,doc_id=1):
        response=self.client.post(BASE+'/extractions',json={'doc_id':doc_id})
        self.assertEqual(response.status_code,202,response.text)
        return store.job(response.json()['id'])

    def execute(self,job,payload=None,side_effect=None):
        doc_id=1
        with store.connect() as c:
            doc_id=c.execute('SELECT doc_id FROM snapshots WHERE id=?',(job['snapshot_id'],)).fetchone()[0]
        with patch.object(flow,'run_model',return_value=(payload or {'statements':[self.fields(doc_id)]},{'test':True}),side_effect=side_effect):
            flow.extract_job(job['id'],evidence.get_document(doc_id),job['snapshot_id'])
        return store.job(job['id'])

    def test_full_review_comparison_notes_and_production_isolation(self):
        before=self.approved(1)
        current=self.approved(2)
        compared=self.comparison(current)
        self.assertEqual(compared['kind'],'numeric_change')
        self.assertEqual(compared['previous']['id'],before['id'])
        self.assertEqual(compared['delta'],10)
        self.assertEqual(self.client.post(BASE+f"/statements/{current['id']}/notes",json={'text':'가격 근거를 더 확인한다'}).status_code,201)
        history=self.client.get(BASE+f"/statements/{current['id']}/history").json()
        self.assertEqual(len(history['reviews']),1)
        self.assertEqual(history['notes'][0]['text'],'가격 근거를 더 확인한다')
        self.assertEqual(store.get_statement(current['id'])['status'],'approved')
        self.assertEqual(self.corpus.read_bytes(),self.original)
        self.assertNotEqual(self.experiment,self.corpus)
        with patch.object(store,'EXPERIMENT_DB',store.DB_PATH):
            with self.assertRaises(RuntimeError):
                with store.connect(): pass

    def test_unknown_speaker_and_missing_attribution_evidence_cannot_be_approved(self):
        s=self.manual(speaker='',attribution='unknown')
        self.assertEqual(self.comparison(s)['kind'],'not_comparable')
        self.assertEqual(self.review(s).status_code,422)
        self.assertEqual(self.review(s,speaker='연구자',attribution='direct',speaker_quote='').status_code,422)
        self.assertEqual(self.review(s,speaker='연구자',attribution='direct',speaker_quote='',note='채널 프로필에서 실명을 확인함: https://example.test/profile').status_code,200)

    def test_non_verbatim_quote_and_forged_speaker_cue_rejected(self):
        s=self.manual()
        for changes in ({'quote':'원문에 없는 조작 문장입니다'},{'speaker_quote':'CEO 김모씨입니다'},{'unit':''}):
            self.assertEqual(self.review(s,**changes).status_code,422)
        self.assertEqual(self.client.post(BASE+'/statements',json=self.fields()|dict(doc_id=1,text_sha256='0'*64)).status_code,409)

    def test_revision_conflicts_and_stale_source_rejection(self):
        s=self.manual()
        self.assertEqual(self.review(s).status_code,200)
        self.assertEqual(self.review(s).status_code,409)
        current=store.get_statement(s['id'])
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute("UPDATE raw_documents SET markdown='수정된 DRAM 전망' WHERE id=1")
        self.assertEqual(self.review(current).status_code,409)
        snapshot=self.client.get(BASE+f"/statements/{s['id']}/evidence").json()
        self.assertIn(current['fields']['quote'],snapshot['text'])
        self.assertEqual(snapshot['text_sha256'],current['document']['text_sha256'])
        response=self.review(current,'rejected',quote='편집 중 내용은 저장하지 않는다')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['fields']['quote'],current['fields']['quote'])
        self.assertEqual(self.comparison(response.json())['kind'],'not_comparable')

    def test_axes_horizons_products_and_conditions_are_not_mixed(self):
        self.approved(1)
        for changes in ({'axis':'acceleration'},{'lens':'valuation'},{'horizon':'2028'},{'product':'hbm'},
                        {'basis':'서버 DDR5 계약가'},{'unit':'% QoQ'},{'speaker':'다른 연구자'},
                        {'target':'Micron'},{'conditions':'공급 증설이 지연되면'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.comparison(self.approved(2,**changes))['kind'],'first_observation')

    def test_unknown_horizon_basis_and_publication_time_hold_comparison(self):
        for changes in ({'horizon':'단기'},{'horizon':'2027-99'},{'horizon':'2027-02-30'},{'basis':'unknown'}):
            self.assertEqual(self.comparison(self.approved(2,**changes))['kind'],'not_comparable')
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute('UPDATE raw_documents SET published_at=NULL WHERE id=3')
        self.assertEqual(self.comparison(self.approved(3))['kind'],'not_comparable')

    def test_future_and_same_time_statements_do_not_become_previous(self):
        self.approved(2)
        first=self.approved(1)
        self.assertEqual(self.comparison(first)['kind'],'first_observation')
        another=self.approved(1)
        self.assertEqual(self.comparison(another)['kind'],'first_observation')

    def test_reposted_identical_quote_is_not_independent_revision(self):
        self.approved(1)
        with closing(sqlite3.connect(self.corpus)) as c, c:
            body=evidence.get_document(1).text
            c.execute('UPDATE raw_documents SET markdown=?,raw_content=? WHERE id=2',(body,body))
        s=self.approved(2,quote=self.fields(1)['quote'],value=10)
        self.assertEqual(self.comparison(s)['kind'],'repetition')

    def test_extraction_is_idempotent_draft_only_and_skips_invalid_quotes(self):
        job=self.queued()
        self.assertEqual(self.queued()['id'],job['id'])
        self.assertEqual(self.submit.call_count,1)
        result=self.execute(job,{'statements':[self.fields(),self.fields(quote='만들어낸 전망 인용문')]})
        self.assertEqual(result['state'],'done')
        self.assertEqual(result['result']['skipped'],1)
        self.assertEqual(len(store.list_statements()),1)
        self.assertEqual(store.list_statements()[0]['status'],'draft')
        self.assertEqual(self.queued()['id'],job['id'])
        self.assertEqual(self.corpus.read_bytes(),self.original)

    def test_failed_model_output_can_retry_without_partial_statements(self):
        job=self.queued()
        self.assertEqual(self.execute(job,{'statements':[self.fields(quote='조작된 문장입니다') ]})['state'],'failed')
        self.assertEqual(store.list_statements(),[])
        self.assertNotEqual(self.queued()['id'],job['id'])

    def test_cancelled_job_cannot_commit_results_even_after_model_returns(self):
        job=self.queued()
        def cancel_during_model(*args):
            flow.cancel(job['id'])
            return {'statements':[self.fields()]},{}
        self.assertEqual(self.execute(job,side_effect=cancel_during_model)['state'],'cancelled')
        self.assertEqual(store.list_statements(),[])
        second=self.queued()
        flow.cancel(second['id'])
        self.assertEqual(self.execute(second)['state'],'cancelled')
        self.assertEqual(store.list_statements(),[])

    def test_queue_limits_derived_sources_and_interrupted_job_recovery(self):
        jobs=[self.queued(i) for i in range(1,5)]
        self.assertEqual(self.client.post(BASE+'/extractions',json={'doc_id':5}).status_code,429)
        self.assertEqual(self.client.post(BASE+'/extractions',json={'doc_id':8}).status_code,422)
        with store.connect() as c:
            c.execute("UPDATE jobs SET updated_at='2000-01-01T00:00:00Z' WHERE id=?",(jobs[0]['id'],))
        self.assertEqual(store.job(jobs[0]['id'])['state'],'failed')
        self.assertEqual(self.client.post(BASE+'/extractions',json={'doc_id':5}).status_code,202)

    def test_extraction_version_change_gets_new_job(self):
        job=self.queued()
        self.execute(job)
        with patch.object(flow,'VERSION','next-version'):
            self.assertNotEqual(self.queued()['id'],job['id'])

    def test_present_posture_can_compare_without_inventing_forecast_period(self):
        posture=dict(lens='position',metric='position',axis='position',horizon='current',basis='현금 비중',value=None,unit='')
        self.approved(1,**posture,direction='up')
        current=self.approved(2,**posture,direction='down')
        result=self.comparison(current)
        self.assertEqual(result['kind'],'direction_change')
        self.assertIn('실제 체결',result['reason'])
        self.assertEqual(self.comparison(self.approved(3,horizon='current'))['kind'],'not_comparable')

    def test_missing_records_and_blank_notes(self):
        for suffix in ('/jobs/missing','/statements/999/comparison','/statements/999/history'):
            self.assertEqual(self.client.get(BASE+suffix).status_code,404)
        self.assertEqual(self.client.post(BASE+'/jobs/missing/cancel',json={}).status_code,404)
        s=self.manual()
        self.assertEqual(self.client.post(BASE+f"/statements/{s['id']}/notes",json={'text':'  '}).status_code,422)


if __name__=='__main__':
    unittest.main()

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline.market_analysis.discovery_research import (
    build_packet, synthesize, validate_synthesis, ResearchError, ModelCancelled, ModelError, _call_model,
)


SCHEMA = """
CREATE TABLE companies(corp_code TEXT,corp_name TEXT,stock_code TEXT,market TEXT,sector TEXT);
CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,source_id TEXT,title TEXT,
 url TEXT,published_at TEXT,fetched_at TEXT,markdown TEXT,raw_content TEXT);
CREATE TABLE entities(id INTEGER PRIMARY KEY,name TEXT,type TEXT,aliases TEXT,status TEXT);
CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER);
CREATE TABLE entity_relations(id INTEGER,src_id INTEGER,dst_id INTEGER,source_doc_id INTEGER,created_at TEXT);
CREATE TABLE transcripts(raw_doc_id INTEGER,ticker TEXT,call_date TEXT,provider TEXT,fiscal_year INTEGER,fiscal_period TEXT);
CREATE TABLE disclosures(rcp_no TEXT,corp_code TEXT,report_nm TEXT,rcept_dt TEXT,fetched_at TEXT,dart_url TEXT,flr_nm TEXT);
CREATE TABLE financial_statements(id INTEGER,corp_code TEXT,bsns_year INTEGER,reprt_code TEXT,fs_div TEXT,
 sj_div TEXT,account_nm TEXT,thstrm_amount TEXT,fetched_at TEXT,ord INTEGER);
CREATE TABLE trade_stats(id INTEGER,hs_code TEXT,period TEXT,export_usd REAL,import_usd REAL,export_wt REAL,import_wt REAL,fetched_at TEXT);
CREATE TABLE trade_follow(hs_code TEXT,item_name TEXT,group_label TEXT,active INTEGER);
CREATE TABLE trade_beneficiaries(hs_code TEXT,stock_code TEXT,reason TEXT,computed_at TEXT);
"""


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"source.sqlite"
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT INTO companies VALUES ('CORP','회사A','000001','KOSPI','반도체')")
        self.conn.execute("INSERT INTO entities VALUES (1,'회사A','company','000001','active')")
        self.conn.commit()
        self.case = {"stock_code": "000001", "name": "회사A", "discovery": {"as_of": "2026-01-01"}}

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def doc(self, identifier, *, source="blog", published="2020-05-01", fetched="2020-05-02", body="회사A 수주 증가 주장. 다만 고객 투자가 지연될 위험이 있다."):
        self.conn.execute("INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?)", (
            identifier, source, f"source/{identifier}", f"회사A 자료 {identifier}", "https://example.com/"+str(identifier),
            published, fetched, body, body))
        self.conn.execute("INSERT INTO entity_links VALUES (?,1)", (identifier,))
        self.conn.commit()

    def packet(self, **kwargs):
        return build_packet(self.path, self.case, question="회사A 반도체 수주와 실적을 조사", **kwargs)

    @staticmethod
    def items(packet, lane):
        return next(entry["items"] for entry in packet["lanes"] if entry["id"] == lane)

    def test_source_is_read_only_and_transaction_closed_before_model(self):
        self.doc(1)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        real_connect = sqlite3.connect
        observed = []
        def connect(database_uri, **kwargs):
            self.assertTrue(database_uri.endswith("?mode=ro"))
            connection = real_connect(database_uri, **kwargs)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM companies")
            connection.rollback()
            observed.append(connection)
            return connection
        with patch("pipeline.market_analysis.discovery_research.sqlite3.connect", side_effect=connect):
            packet = self.packet()
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.assertRaises(sqlite3.ProgrammingError):
            observed[0].execute("SELECT 1")
        self.assertIn("수주 증가", self.items(packet, "market")[0]["excerpt"])
        self.assertEqual(packet["discovery"], self.case["discovery"])

    def test_future_unknown_and_late_acquired_documents_are_fenced(self):
        self.doc(1)
        self.doc(2, published="2099-01-01")
        self.doc(3, published=None)
        self.doc(4, fetched="2020-07-01")
        self.doc(5, published="2020-06-02T00:00:00+09:00")
        packet = self.packet(as_of="2020-06-01")
        self.assertEqual([i["id"] for i in self.items(packet, "market")], ["doc:1"])
        warnings = " ".join(packet["warnings"])
        self.assertIn("공개 시점 미확인", warnings)
        self.assertIn("이후 확보", warnings)
        with self.assertRaises(ResearchError):
            self.packet(as_of="2099-01-01")

    def test_transcript_guessed_dates_and_future_call_are_not_historical_facts(self):
        self.doc(1, source="transcript", body="회사A 경영진: 투자 증가. Analyst: demand risk?")
        self.doc(2, source="transcript", body="회사A 미래 콜 내용")
        self.conn.execute("INSERT INTO transcripts VALUES (1,'AAA','2020-05-01','alphavantage',2020,'Q1')")
        self.conn.execute("INSERT INTO transcripts VALUES (2,'AAA','2099-01-01','alphavantage',2099,'Q1')")
        self.conn.commit()
        current = self.packet()
        self.assertEqual([i["id"] for i in self.items(current, "call")], ["doc:1"])
        self.assertEqual(self.items(current, "call")[0]["time_precision"], "unverified")
        self.assertEqual(self.items(self.packet(as_of="2020-06-01"), "call"), [])

    def test_historical_retrieval_is_not_crowded_out_by_new_documents(self):
        self.doc(1)
        for identifier in range(2,202):
            self.doc(identifier,published="2021-01-01",body=f"회사A 새 자료 {identifier}")
        self.assertEqual([i["id"] for i in self.items(self.packet(as_of="2020-06-01"),"market")],["doc:1"])

    def test_zero_missing_loss_and_periods_remain_distinct(self):
        from datetime import date
        year = date.today().year-1
        for identifier, account, value in [(1,"매출액","0"),(2,"영업이익","-1,234"),(3,"당기순이익","-")]:
            self.conn.execute("INSERT INTO financial_statements VALUES (?,?,?,?,?,?,?,?,?,?)", (
                identifier,"CORP",year,"11012","CFS","IS",account,value,"2020-05-01",identifier))
        self.conn.commit()
        rows = self.items(self.packet(), "earnings")
        self.assertEqual(len(rows),1)
        values = {v["account"]:v["amount"] for v in rows[0]["values"]}
        self.assertEqual(values,{"매출액":0,"영업이익":-1234,"당기순이익":None})
        self.assertIn("2분기",rows[0]["title"])
        self.assertEqual(rows[0]["published_at"],None)
        self.assertEqual(self.items(self.packet(as_of="2020-06-01"),"earnings"),[])

    def test_trade_bad_codes_overlap_missing_and_unverified_company_link(self):
        for code in ("8542","854232","bad' SQL"):
            self.conn.execute("INSERT INTO trade_follow VALUES (?,'반도체','반도체',1)",(code,))
            self.conn.execute("INSERT INTO trade_beneficiaries VALUES (?,'000001','모델이 제안한 수혜','2020-01-01')",(code,))
            self.conn.execute("INSERT INTO trade_stats VALUES (1,?,'2020-01',0,NULL,100,NULL,'2020-02-01')",(code,))
        self.conn.commit()
        packet=self.packet()
        items=self.items(packet,"trade")
        self.assertEqual({i["hs_code"] for i in items},{"8542","854232"})
        self.assertTrue(all(i["mapping_status"]=="unverified" for i in items))
        self.assertTrue(all(any("합산하지" in warning for warning in i["warnings"]) for i in items))
        self.assertEqual(items[0]["values"][0]["export_usd"],0)
        self.assertIsNone(items[0]["values"][0]["import_usd"])
        self.assertEqual(self.items(self.packet(as_of="2020-06-01"),"trade"),[])

    def test_duplicate_content_does_not_become_independent_evidence(self):
        self.doc(1)
        self.doc(2)
        packet=self.packet()
        items=[item for entry in packet["lanes"] for item in entry["items"] if item["id"].startswith("doc:")]
        self.assertEqual(len(items),1)

    def test_unknown_citations_and_unsupported_claims_rejected(self):
        self.doc(1)
        packet=self.packet()
        result={"summary":"작성자가 수주 증가를 주장했다. [doc:1]","claims":[{"text":"작성자의 주장", "kind":"fact","evidence_ids":["doc:1"]}],"questions":["실제 수주 확인?"],"limitations":["독립 검증 없음"]}
        self.assertEqual(validate_synthesis(result,packet)["claims"][0]["kind"],"source_claim")
        for ids in (["doc:999"],[]):
            result["claims"][0]["evidence_ids"]=ids
            with self.assertRaises(ResearchError): validate_synthesis(result,packet)
        result["claims"][0]["evidence_ids"]=["doc:1"]
        result["summary"]="존재하지 않는 원문 [doc:999]"
        with self.assertRaises(ResearchError): validate_synthesis(result,packet)

    def test_model_error_is_visible_and_no_fabricated_fallback(self):
        self.doc(1)
        with patch("pipeline.market_analysis.discovery_research._call_model", side_effect=ModelError("provider failed")):
            with self.assertRaisesRegex(ModelError,"provider failed"): synthesize(self.packet())
        with patch("pipeline.market_analysis.discovery_research._call_model") as call:
            with self.assertRaises(ModelCancelled): synthesize(self.packet(),cancel=lambda: True)
            call.assert_not_called()

    def test_model_temp_symlink_ancestor_is_canonicalized_before_preflight(self):
        real_parent=Path(self.temp.name)/"actual"
        real_parent.mkdir()
        linked_parent=Path(self.temp.name)/"linked"
        linked_parent.symlink_to(real_parent,target_is_directory=True)
        real_tempdir=tempfile.TemporaryDirectory
        def make_tempdir(**kwargs):
            return real_tempdir(dir=linked_parent,**kwargs)
        seen=[]
        def preflight(adapter):
            seen.append(adapter.cwd)
            self.assertEqual(adapter.cwd,adapter.cwd.resolve())
            self.assertTrue(adapter.cwd.is_relative_to(real_parent.resolve()))
        with patch("pipeline.market_analysis.discovery_research.tempfile.TemporaryDirectory",side_effect=make_tempdir), \
             patch("pipeline.market_analysis.discovery_research.ClaudeModel._preflight",preflight):
            # Exercises the actual secure-directory constructor and preflight,
            # then cancellation prevents any provider call.
            with self.assertRaises(ModelCancelled):
                _call_model({},lambda: True)
        self.assertEqual(len(seen),1)

    @staticmethod
    def model_result(evidence="doc:1"):
        return {"summary":f"작성자가 수주 증가를 주장했다. [{evidence}]",
                "claims":[{"text":"수주 증가 주장", "kind":"source_claim", "evidence_ids":[evidence]}],
                "questions":["실제 수주가 확인되는가?"],"limitations":["독립 확인 없음"]}

    def test_invalid_citation_gets_one_repair_with_same_packet_remaining_budget_and_time(self):
        self.doc(1)
        packet=self.packet()
        clock=[0.0]
        observed=[]
        invalid=self.model_result("doc:unknown")
        def model(received,cancel,**kwargs):
            self.assertIs(received,packet)
            observed.append(kwargs)
            clock[0]+=20
            return (invalid if len(observed)==1 else self.model_result()),.25
        with patch("pipeline.market_analysis.discovery_research._call_model",side_effect=model), \
             patch("pipeline.market_analysis.discovery_research.time.monotonic",side_effect=lambda:clock[0]):
            result=synthesize(packet)
        self.assertEqual(result["attempts"],2)
        self.assertEqual(result["cost_usd"],.5)
        self.assertEqual(observed[0]["budget"],1.5)
        self.assertEqual(observed[1]["budget"],1.25)
        self.assertEqual(observed[0]["timeout"],180)
        self.assertEqual(observed[1]["timeout"],160)
        self.assertEqual(observed[1]["repair"]["previous_output"],invalid)
        self.assertEqual(observed[1]["repair"]["invalid_ids"],["doc:unknown"])
        self.assertEqual(result["claims"][0]["evidence_ids"],["doc:1"])

    def test_repeated_invalid_citations_fail_closed_with_cost_and_validation_metadata(self):
        self.doc(1)
        with patch("pipeline.market_analysis.discovery_research._call_model",return_value=(self.model_result("doc:unknown"),.2)) as model:
            with self.assertRaises(ResearchError) as failed:
                synthesize(self.packet())
        self.assertEqual(model.call_count,2)
        error=failed.exception
        self.assertEqual(error.attempts,2)
        self.assertAlmostEqual(error.cost_usd,.4)
        self.assertEqual(error.known_cost_usd,error.cost_usd)
        self.assertEqual(len(error.validation_errors),2)
        self.assertEqual(error.invalid_ids,["doc:unknown"])

    def test_cancel_during_repair_stops_and_preserves_known_cost(self):
        self.doc(1)
        with patch("pipeline.market_analysis.discovery_research._call_model",side_effect=[
                (self.model_result("doc:unknown"),.2),ModelCancelled("cancelled during repair")]) as model:
            with self.assertRaises(ModelCancelled) as failed:
                synthesize(self.packet())
        self.assertEqual(model.call_count,2)
        self.assertIsNone(failed.exception.cost_usd)
        self.assertEqual(failed.exception.known_cost_usd,.2)
        self.assertEqual(failed.exception.attempts,2)
        self.assertEqual(len(failed.exception.validation_errors),1)

    def test_repair_cannot_exceed_shared_cost_or_time_budget(self):
        self.doc(1)
        packet=self.packet()
        for cost,elapsed in [(1.5,20),(.2,170)]:
            clock=[0.0]
            def model(*args,**kwargs):
                clock[0]=elapsed
                return self.model_result("doc:unknown"),cost
            with patch("pipeline.market_analysis.discovery_research._call_model",side_effect=model) as called, \
                 patch("pipeline.market_analysis.discovery_research.time.monotonic",side_effect=lambda:clock[0]):
                with self.assertRaises(ResearchError) as failed:
                    synthesize(packet)
            self.assertEqual(called.call_count,1)
            self.assertEqual(failed.exception.attempts,1)
            self.assertEqual(failed.exception.cost_usd,cost)
            self.assertEqual(len(failed.exception.validation_errors),1)

    def test_user_judgment_is_preserved_separately_from_evidence(self):
        note={"revision":2,"reason":"고객 투자 회복 가설","assumptions":"수주가 먼저 회복", "invalidation":"수주 취소", "watch_items":["수주 잔고 변화"]}
        self.case["notes"]=[{"revision":1,"reason":"옛 가설"},note]
        self.doc(1)
        packet=self.packet()
        self.assertEqual(packet["user_judgment"]["revision"],2)
        self.assertEqual(packet["user_judgment"]["authorship"],"user")
        self.assertEqual(packet["user_judgment"]["invalidation"],"수주 취소")
        self.assertEqual(self.case["notes"][-1],note)
        self.assertFalse(any(item["id"].startswith("note:") for lane in packet["lanes"] for item in lane["items"]))

    def verified_discovery(self):
        self.case["source_run_id"]="verified-run-1"
        self.case["discovery"]={"as_of":"2020-05-31","verification":{"status":"matched"},
            "warnings":["공식 거래소 달력 미확보"],
            "evidence":{"code":"000001","name":"회사A","breakout_date":"2020-03-01","high52_date":"2020-03-02",
                "checks":{"pattern":{"status":"pass","version":"consecutive-pivots-v1"},
                    "high52":{"status":"pass","date":"2020-03-02","basis":"close"},
                    "ma":{"status":"pass","period":20,"hold_days":14,"price_basis":"close"},
                    "market_cap":{"status":"unverified","value":1000000000,"minimum":500000000,"date":"2020-05-31"},
                    "calendar":{"status":"unverified"}},
                "pattern":{"breakout_date":"2020-03-01"}}}

    def test_verified_discovery_is_separate_citable_host_evidence_with_exact_window(self):
        self.verified_discovery()
        packet=self.packet()
        item=self.items(packet,"market")[0]
        self.assertEqual(item["id"],"discovery:verified-run-1")
        self.assertEqual(item["source"],"Explorer 독립검증 계산")
        self.assertEqual(item["kind"],"fact")
        self.assertEqual(item["as_of"],"2020-05-31")
        self.assertIn("2020-03-01",item["excerpt"])
        self.assertIn("2020-03-02",item["excerpt"])
        self.assertIn("최근 14관측일",item["excerpt"])
        self.assertIn("돌파 이후 전기간을 유지했다는 뜻이 아닙니다",item["excerpt"])
        self.assertNotIn("market_cap",item["passed_checks"])
        self.assertNotIn("calendar",item["passed_checks"])
        result=self.model_result("discovery:verified-run-1")
        result["claims"][0]["kind"]="fact"
        self.assertEqual(validate_synthesis(result,packet)["claims"][0]["kind"],"fact")
        result["summary"]="계산 결과 [discovery:forged]"
        with self.assertRaises(ResearchError): validate_synthesis(result,packet)

    def test_unverified_mismatched_or_future_discovery_is_not_evidence(self):
        self.verified_discovery()
        original=json.loads(json.dumps(self.case))
        for invalid in (None,"matched",{"status":"mismatch"},{"status":"pending"}):
            self.case=json.loads(json.dumps(original))
            self.case["discovery"]["verification"]=invalid
            self.assertEqual(self.items(self.packet(),"market"),[])
        self.case=json.loads(json.dumps(original))
        self.case["discovery"]["evidence"]["code"]="999999"
        self.assertEqual(self.items(self.packet(),"market"),[])
        self.case=json.loads(json.dumps(original))
        self.assertEqual(self.items(self.packet(as_of="2020-04-01"),"market"),[])
        self.case["discovery"]["evidence"]["checks"]={"ma":{"status":"fail","period":20,"hold_days":14,"price_basis":"close"}}
        self.assertEqual(self.items(self.packet(),"market"),[])

    def test_no_evidence_returns_explicit_unknown_without_model(self):
        with patch("pipeline.market_analysis.discovery_research._call_model") as call:
            result=synthesize(self.packet())
            call.assert_not_called()
        self.assertEqual(result["claims"][0]["kind"],"unknown")
        self.assertEqual(result["model_status"],"not_called_no_evidence")

    def test_title_only_and_excerpt_offsets_are_honest(self):
        self.doc(1,body="")
        self.doc(2,body="회사A "+"서론 "*3000+"수주 감소 위험 "+"후기 "*3000)
        packet=self.packet()
        items={i["id"]:i for i in self.items(packet,"market")}
        self.assertEqual(items["doc:1"]["read_scope"],"title_only")
        self.assertEqual(items["doc:2"]["read_scope"],"excerpt")
        self.assertLess(len(items["doc:2"]["excerpt"]),2300)
        self.assertIn("수주 감소 위험",items["doc:2"]["excerpt"])
        self.assertTrue(items["doc:2"]["excerpt_ranges"])


if __name__ == "__main__":
    unittest.main()

"""Trusted missing-data collection: scope, retries, cancellation and provenance."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pipeline.market_analysis.discovery_preparation import (
    DartClient, MAX_REQUESTS, PreparationCancelled, PreparationError, ReceiptCache,
    prepare_company, report_periods,
)
from pipeline.market_analysis.discovery_research import build_packet
from backend.tests import test_market_discovery as discovery_tests


SCHEMA = """
CREATE TABLE companies(corp_code TEXT PRIMARY KEY,stock_code TEXT,corp_name TEXT,market TEXT,sector TEXT);
CREATE TABLE financial_statements(id INTEGER PRIMARY KEY,corp_code TEXT,bsns_year INTEGER,reprt_code TEXT,
 fs_div TEXT,sj_div TEXT,account_nm TEXT,thstrm_amount TEXT,frmtrm_amount TEXT,bfefrmtrm_amount TEXT,ord INTEGER,
 fetched_at TEXT DEFAULT (datetime('now')), UNIQUE(corp_code,bsns_year,reprt_code,fs_div,sj_div,account_nm));
CREATE TABLE disclosures(rcp_no TEXT PRIMARY KEY,corp_code TEXT,corp_name TEXT,report_nm TEXT,rcept_dt TEXT,
 flr_nm TEXT,rm TEXT,kind TEXT,dart_url TEXT,fetched_at TEXT DEFAULT (datetime('now')));
CREATE TABLE cache_meta(cache_key TEXT PRIMARY KEY,fetched_at TEXT,expires_at TEXT);
CREATE TABLE immutable_source(id INTEGER,value TEXT);
INSERT INTO companies VALUES ('01234567','123456','검증회사','KOSDAQ','반도체');
INSERT INTO companies VALUES ('99999999','999999','다른회사','KOSPI','자동차');
INSERT INTO immutable_source VALUES (1,'가격·원문·사용자 기록 불변');
INSERT INTO financial_statements(corp_code,bsns_year,reprt_code,fs_div,sj_div,account_nm,thstrm_amount,ord)
 VALUES ('99999999',2025,'11011','CFS','IS','매출액','777',1);
"""


class FakeDart:
    def __init__(self):
        self.requests = 0
        self.calls = []
        self.action = None
        self.ofs = False

    def get(self, endpoint, params):
        self.requests += 1
        self.calls.append((endpoint, copy.deepcopy(params)))
        if self.action:
            result = self.action(endpoint, params)
            if result is not None:
                return result
        if endpoint == "list.json":
            return {"status": "000", "total_page": 1, "list": [{"corp_code": params["corp_code"],
                "rcept_no": "20260814000001", "rcept_dt": "20260814", "report_nm": "반기보고서", "corp_name": "검증회사"}]}
        if self.ofs and params["fs_div"] == "CFS":
            return {"status": "013"}
        return {"status": "000", "list": [{**params, "rcept_no": "20260814000001", "currency": "KRW",
            "sj_div": sj, "account_nm": account, "thstrm_amount": "1,000", "ord": index}
            for index, (sj, account) in enumerate((('IS', '매출액'), ('BS', '자산총계'), ('CF', '영업활동현금흐름')))]}


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "source.sqlite"
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(SCHEMA)
        self.client = FakeDart()
        self.case = {"stock_code": "123456", "name": "검증회사", "notes": [], "discovery": {"as_of": "2026-09-18"}}
        self.key = patch("config.DART_API_KEY", "test-only-not-a-real-key")
        self.key.start()

    def tearDown(self):
        self.key.stop()
        self.temp.cleanup()

    def prepare(self, **kwargs):
        return prepare_company(self.path, self.root, self.case, today=date(2026, 9, 19),
                               client_factory=lambda *args: self.client, **kwargs)

    def rows(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            return conn.execute(sql, params).fetchall()

    def test_scope_cfs_priority_insert_only_and_repeat_reuses_success(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO financial_statements(corp_code,bsns_year,reprt_code,fs_div,sj_div,account_nm,thstrm_amount) VALUES ('01234567',2026,'11012','CFS','IS','매출액','555')")
        unrelated = self.rows("SELECT * FROM financial_statements WHERE corp_code='99999999'")
        schema = self.rows("SELECT type,name,sql FROM sqlite_master ORDER BY name")
        snapshots = []
        result = self.prepare(progress=snapshots.append)
        self.assertEqual(result["items"][0]["status"], "collected")
        self.assertIn("최신 정정 여부", result["items"][0]["detail"])
        self.assertTrue(all(params["corp_code"] == "01234567" for _, params in self.client.calls))
        self.assertFalse(any(params.get("fs_div") == "OFS" for _, params in self.client.calls))
        self.assertLessEqual(len(self.client.calls), MAX_REQUESTS)
        self.assertEqual(self.rows("SELECT * FROM financial_statements WHERE corp_code='99999999'"), unrelated)
        self.assertEqual(self.rows("SELECT thstrm_amount FROM financial_statements WHERE corp_code='01234567' AND bsns_year=2026 AND reprt_code='11012' AND sj_div='IS'"), [("555",)])
        self.assertEqual(self.rows("SELECT type,name,sql FROM sqlite_master ORDER BY name"), schema)
        count = len(self.client.calls)
        self.prepare()
        self.assertEqual(len(self.client.calls), count)
        self.assertTrue(any(item["items"][0]["status"] == "collecting" for item in snapshots))
        self.assertEqual(self.rows("SELECT * FROM immutable_source"), [(1, "가격·원문·사용자 기록 불변")])

    def test_official_no_data_falls_back_to_ofs_and_is_not_failure(self):
        self.client.ofs = True
        result = self.prepare()
        self.assertEqual(result["items"][0]["status"], "collected")
        self.assertEqual(self.rows("SELECT DISTINCT fs_div FROM financial_statements WHERE corp_code='01234567'"), [("OFS",)])
        count = self.client.requests
        self.prepare()
        self.assertEqual(self.client.requests, count)

    def test_failed_attempt_not_cached_and_old_negative_cache_does_not_block(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO cache_meta VALUES ('finstate:01234567:2026:11012:CFS','2026-09-19','2099-01-01')")
        def fail(endpoint, params):
            if endpoint == "fnlttSinglAcntAll.json":
                raise PreparationError("일시적 연결 실패")
        self.client.action = fail
        first = self.prepare()
        self.assertEqual(first["items"][0]["status"], "failed")
        with closing(sqlite3.connect(self.root / "preparation.sqlite")) as conn, conn:
            bodies = [json.loads(row[0]) for row in conn.execute("SELECT body FROM receipts")]
        self.assertEqual(len(bodies), 1)  # only successful disclosure response
        self.client.action = None
        second = self.prepare()
        self.assertEqual(second["items"][0]["status"], "collected")
        self.assertGreater(len(self.rows("SELECT id FROM financial_statements WHERE corp_code='01234567'")), 0)

    def test_cancel_after_response_stops_before_any_source_write(self):
        cancelled = [False]
        original = self.path.read_bytes()
        def stop(endpoint, params):
            cancelled[0] = True
        self.client.action = stop
        with self.assertRaises(PreparationCancelled):
            self.prepare(cancel=lambda: cancelled[0])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.client.requests, 1)

    def test_historical_research_does_not_collect_today_or_create_receipts(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = self.prepare(as_of="2026-09-18")
        self.assertEqual(self.client.calls, [])
        self.assertFalse((self.root / "preparation.sqlite").exists())
        self.assertEqual(result["items"][0]["status"], "unsupported")
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_mismatched_provider_company_never_enters_cache_or_source(self):
        self.client.action = lambda endpoint, params: {"status": "000", "list": [{"corp_code": "99999999"}]} if endpoint.startswith("fnltt") else {"status": "013"}
        result = self.prepare()
        self.assertEqual(result["items"][0]["status"], "failed")
        self.assertEqual(self.rows("SELECT id FROM financial_statements WHERE corp_code='01234567'"), [])
        with closing(sqlite3.connect(self.root / "preparation.sqlite")) as conn, conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM receipts").fetchone()[0], 1)

    def test_concurrent_preparation_coalesces_through_company_lock_and_cache(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.prepare(), range(2)))
        self.assertEqual(self.client.requests, len(report_periods(date(2026, 9, 19))) + 1)
        self.assertEqual({r["items"][0]["status"] for r in results}, {"available", "collected"})

    def test_receipt_dates_and_account_semantics_reach_frozen_packet(self):
        preparation = self.prepare()
        packet = build_packet(self.path, self.case, question="실적과 현금흐름", preparation=preparation)
        financials = [item for lane in packet["lanes"] for item in lane["items"] if item["id"].startswith("financial:")]
        self.assertTrue(financials)
        item = financials[0]
        self.assertEqual(item["published_at"], "2026-08-14")
        self.assertEqual(item["collection"]["receipt_numbers"], ["20260814000001"])
        self.assertEqual({number["statement"] for number in item["values"]}, {"IS", "BS", "CF"})
        self.assertTrue(any("현금흐름은 연초부터 누적" in warning for warning in item["warnings"]))
        historical = build_packet(self.path, self.case, question="당시 실적", as_of="2026-09-18", preparation=preparation)
        self.assertFalse(any(item["id"].startswith("financial:") for lane in historical["lanes"] for item in lane["items"]))

    def test_request_budget_and_timeout_cannot_be_bypassed(self):
        client = DartClient("credential", lambda: False, time.monotonic() + 90)
        client.requests = MAX_REQUESTS
        with patch("requests.get") as network:
            with self.assertRaises(PreparationError):
                client.get("list.json", {})
            network.assert_not_called()
        client = DartClient("credential", lambda: False, time.monotonic() - 1)
        with patch("requests.get") as network:
            with self.assertRaises(PreparationError):
                client.get("list.json", {})
            network.assert_not_called()

    def test_provider_error_never_leaks_credential(self):
        import requests
        client = DartClient("secret-credential", lambda: False, time.monotonic() + 90)
        with patch("requests.get", side_effect=requests.Timeout("https://example.com?crtfc_key=secret-credential")):
            with self.assertRaises(PreparationError) as caught:
                client.get("list.json", {})
        self.assertNotIn("secret", str(caught.exception))


class OneClickResearchTests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    tearDown = discovery_tests.DiscoveryTests.tearDown
    case = discovery_tests.DiscoveryTests.case
    def test_one_click_concurrent_create_is_atomic_and_revisit_does_not_rerun(self):
        payload = {"run_id": self.run["id"], "stock_code": "000001", "question": "조사", "start_research": True, "request_key": "one-click-0001"}
        with ThreadPoolExecutor(4) as pool:
            cases = list(pool.map(lambda _: self.service.create_case(payload), range(8)))
        self.assertEqual(len({case["id"] for case in cases}), 1)
        self.assertEqual(len(self.service.store.list("research")), 1)
        self.assertEqual(cases[0]["research_runs"][0]["phase"], "preparing")
        self.assertEqual(cases[0]["discovery"]["as_of"], "2026-09-18")
        self.assertNotEqual(cases[0]["research_runs"][0]["as_of"], None)
        reopened = self.service.create_case({**payload, "request_key": "another-tab-0001"})
        self.assertEqual(reopened["id"], cases[0]["id"])
        self.assertEqual(len(self.service.store.list("research")), 1)

    def test_get_does_not_prepare_write_or_queue_jobs(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import discovery
        case = self.case()
        before = self.service.store.path.read_bytes()
        with patch.object(discovery, "_service", self.service), patch.object(self.service, "preparer") as prepare:
            app = FastAPI()
            app.include_router(discovery.router)
            client = TestClient(app)
            self.assertEqual(client.get("/discovery/cases/" + case["id"]).status_code, 200)
            self.assertEqual(client.get("/discovery/cases").status_code, 200)
            prepare.assert_not_called()
        self.assertEqual(self.service.store.list("research"), [])
        self.assertEqual(self.service.store.path.read_bytes(), before)

    def test_preparation_failure_is_reported_while_existing_evidence_is_researched(self):
        case = self.case()
        self.service.preparer = lambda *args, **kwargs: {"status": "partial", "items": [{"id": "financials", "label": "재무제표", "status": "failed", "detail": "연결 실패"}]}
        self.service.packet_builder = lambda *args, **kwargs: {"lanes": [{"id": "market", "status": "partial", "items": [{"id": "doc:1"}]}], "warnings": []}
        self.service.synthesizer = lambda packet, **kwargs: {"summary": "기존 자료로 조사", "claims": [], "questions": [], "limitations": []}
        run = self.service.research(case["id"], {"question": "조사", "request_key": "prepare-error-001"})
        self.service._execute(run["id"])
        result = self.service.store.get("research", run["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(result["result"]["summary"], "기존 자료로 조사")
        self.assertIn("재무제표: 연결 실패", result["packet"]["warnings"])


if __name__ == "__main__":
    unittest.main()

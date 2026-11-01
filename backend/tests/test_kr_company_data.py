"""국내 도시에 원천 수집 — 대상 순서·DART 예산·멱등·실패 상태·밸류 원천 교체.

2026-10-16 실측: 재무 19개사(발견 조사 버튼에서만 수집), 공시 09-16 정지(열 때만 수집하던 탭이 내비에서 빠짐),
밸류 09-07 정지(네이버 시세 표가 SPA로 이동해 0건인데 ok), 종목 마스터 07-06(수동 시드뿐).
"""
import importlib.util
import io
import pathlib
import shutil
import tempfile
import unittest
import zipfile
from datetime import date
from unittest.mock import patch

import requests

import database
from pipeline import kr_company_data as kr
from services import market_valuation as mv

TODAY = date(2026, 10, 16)


class FakeResp:
    def __init__(self, body=None, content=b"", exc=None):
        self._body, self.content, self._exc = body, content, exc

    def raise_for_status(self):
        if self._exc:
            raise self._exc

    def json(self):
        return self._body


class FakeDart:
    """endpoint·params로 응답을 고른다. calls에 (endpoint, params)를 남긴다."""
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def get(self, url, params=None, timeout=None):
        endpoint = url.rsplit("/", 1)[-1]
        p = {k: v for k, v in (params or {}).items() if k != "crtfc_key"}
        self.calls.append((endpoint, p))
        return self.handler(endpoint, p)


def fin_rows(year, rc, revenue):
    return [
        {"sj_div": "IS", "account_nm": "수익(매출액)", "thstrm_amount": str(revenue), "ord": 1, "rcept_no": "x"},
        {"sj_div": "IS", "account_nm": "영업이익(손실)", "thstrm_amount": str(revenue // 10), "ord": 2, "rcept_no": "x"},
        {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "1000", "ord": 3, "rcept_no": "x"},
    ]


class DbCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db_patch = patch.object(database, "DB_PATH", pathlib.Path(self.dir) / "t.db")
        self.db_patch.start()
        database.init_db()
        self.conn = database.get_connection()
        self.conn.executemany("INSERT INTO companies (corp_code, corp_name, stock_code) VALUES (?, ?, ?)", [
            ("00000001", "보유사", "000001"), ("00000002", "관심사", "000002"),
            ("00000003", "대형사", "000003"), ("00000004", "중형사", "000004"), ("00000005", "소형사", "000005"),
        ])
        # 시총: 3 > 4 > 1 > 5 > 2
        self.conn.executemany("INSERT INTO stock_prices (stock_code, trade_date, close, market_cap) VALUES (?, '2026-10-15', 100, ?)",
                              [("000003", 9e13), ("000004", 5e13), ("000001", 3e13), ("000005", 1e12), ("000002", 1e11)])
        self.conn.execute("INSERT INTO stock_groups (id, name, kind) VALUES (1, '내 계좌', 'portfolio'), (2, '관심', 'watch')")
        self.conn.execute("INSERT INTO stock_group_members (group_id, stock_code) VALUES (2, '000002'), (1, '000001')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.db_patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def client(self, handler, budget=1000):
        fake = FakeDart(handler)
        return kr.DartClient("key", budget, session=fake, pause=0), fake


class TargetTests(DbCase):
    def test_groups_first_then_market_cap_without_duplicates(self):
        got = [(t["stock_code"], t["tier"]) for t in kr.targets(self.conn, top_n=3)]
        self.assertEqual(got, [("000001", "portfolio"), ("000002", "watch"), ("000003", "market_cap"), ("000004", "market_cap")])


class FinancialTests(DbCase):
    def handler(self, endpoint, p):
        year, rc = int(p["bsns_year"]), p["reprt_code"]
        revenue = {"11013": 100, "11012": 110, "11014": 120, "11011": 450}[rc] * (year - 2020)
        return FakeResp({"status": "000", "list": fin_rows(year, rc, revenue)})

    def test_due_periods_are_newest_first_and_skip_unfinished_quarters(self):
        periods = kr.due_periods(TODAY, years=1)
        self.assertEqual(periods[:3], [(2026, "11012"), (2026, "11013"), (2025, "11011")])
        self.assertNotIn((2026, "11014"), periods)   # 3분기는 09-30에 끝나 제출 전 — 10-30부터 묻는다
        self.assertEqual(len(periods), 6)
        self.assertIn((2026, "11014"), kr.due_periods(date(2026, 10, 31), years=0))
        self.assertNotIn((2025, "11011"), kr.due_periods(date(2026, 2, 28), years=1))   # 연간은 말일+60일부터

    def test_budget_stops_the_run_and_the_next_run_resumes_without_refetching(self):
        tgts = kr.targets(self.conn, top_n=0)[:1]
        client, fake = self.client(self.handler, budget=5)
        first = kr.collect_financials(self.conn, client, tgts, TODAY, years=1)
        self.assertEqual(first["calls"], 5)
        self.assertEqual(first["periods_added"], 5)
        self.assertEqual(first["budget_exhausted"], 1)
        self.assertEqual(first["remaining_periods"], 1)
        self.assertNotIn("status", first)     # 예산 소진은 실패가 아니다

        client2, fake2 = self.client(self.handler, budget=100)
        second = kr.collect_financials(self.conn, client2, tgts, TODAY, years=1)
        self.assertEqual(second["periods_added"], 1)
        asked = {(p["bsns_year"], p["reprt_code"]) for _, p in fake2.calls}
        self.assertEqual(asked, {("2025", "11013")})   # 저장된 기간은 다시 묻지 않는다

        client3, fake3 = self.client(self.handler)
        kr.collect_financials(self.conn, client3, tgts, TODAY, years=1)
        self.assertEqual(fake3.calls, [])

    def test_cfs_missing_falls_back_to_ofs_and_read_path_applies_dart_rules(self):
        def handler(endpoint, p):
            if p["fs_div"] == "CFS":
                return FakeResp({"status": "013", "message": "조회된 데이타가 없습니다."})
            return self.handler(endpoint, p)
        client, fake = self.client(handler)
        tgts = [{"stock_code": "000001", "corp_code": "00000001", "tier": "portfolio"}]
        r = kr.collect_financials(self.conn, client, tgts, date(2026, 4, 1), years=1)
        self.assertEqual(r["periods_added"], 4)   # 2025 Q1·H1·Q3·연간 (2026 Q1은 04-30부터)
        divs = {x[0] for x in self.conn.execute("SELECT DISTINCT fs_div FROM financial_statements")}
        self.assertEqual(divs, {"OFS"})

        from services.dart_service import _build_financial_response
        with patch("services.dart_service.get_connection", database.get_connection):
            res = _build_financial_response("00000001", "IS", "quarterly", 2025, 2025, "OFS")
        self.assertEqual(res["periods"], ["25.03", "25.06", "25.09", "25.12"])
        revenue = next(row for row in res["rows"] if row["account_nm"] == "매출액")   # 수익(매출액) → 매출액
        self.assertEqual(revenue["values"], ["500", "550", "600", str(2250 - 500 - 550 - 600)])  # Q4 = 연간 − (Q1+Q2+Q3)

    def test_unpublished_periods_are_negative_cached(self):
        client, fake = self.client(lambda e, p: FakeResp({"status": "013"}))
        tgts = [{"stock_code": "000001", "corp_code": "00000001", "tier": "portfolio"}]
        r = kr.collect_financials(self.conn, client, tgts, TODAY, years=0)
        self.assertEqual(r["no_data"], 2)
        self.assertEqual(len(fake.calls), 4)   # 기간마다 CFS·OFS
        client2, fake2 = self.client(lambda e, p: FakeResp({"status": "013"}))
        kr.collect_financials(self.conn, client2, tgts, TODAY, years=0)
        self.assertEqual(fake2.calls, [])

    def test_quota_exceeded_stops_with_error_status(self):
        client, fake = self.client(lambda e, p: FakeResp({"status": "020", "message": "요청 제한을 초과하였습니다."}))
        r = kr.collect_financials(self.conn, client, kr.targets(self.conn, 3), TODAY)
        self.assertEqual(r["status"], "error")
        self.assertIn("020", r["reason"])
        self.assertEqual(len(fake.calls), 1)

    def test_single_network_failure_is_partial_and_message_has_no_key(self):
        n = {"i": 0}

        def handler(endpoint, p):
            n["i"] += 1
            if n["i"] == 1:
                return FakeResp(exc=requests.ConnectionError("https://opendart.fss.or.kr/api/x?crtfc_key=SECRET"))
            return self.handler(endpoint, p)
        client, _ = self.client(handler)
        r = kr.collect_financials(self.conn, client, kr.targets(self.conn, 0)[:1], TODAY, years=0)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(r["failed"], 1)
        self.assertNotIn("SECRET", str(r))

    def test_repeated_network_failures_abort_as_error(self):
        client, fake = self.client(lambda e, p: FakeResp(exc=requests.ConnectionError("down")))
        r = kr.collect_financials(self.conn, client, kr.targets(self.conn, 3), TODAY)
        self.assertEqual(r["status"], "error")
        self.assertEqual(len(fake.calls), kr.MAX_NET_FAILS)


class DisclosureTests(DbCase):
    def handler(self, endpoint, p):
        if "corp_code" in p:
            return FakeResp({"status": "000", "total_page": 1, "list": [
                {"rcept_no": f"2026010{p['corp_code'][-1]}000001", "corp_code": p["corp_code"], "corp_name": "x",
                 "report_nm": "분기보고서", "rcept_dt": "20260105"}]})
        if p["corp_cls"] == "K":
            return FakeResp({"status": "013"})
        return FakeResp({"status": "000", "total_page": 2, "list": [
            {"rcept_no": f"20261015{p['page_no']:06d}", "corp_code": "00000003", "corp_name": "대형사",
             "report_nm": "주요사항보고서", "rcept_dt": "20261015"},
            {"rcept_no": f"20261015{p['page_no']:06d}9", "corp_code": "99999999", "corp_name": "비상장",
             "report_nm": "감사보고서", "rcept_dt": "20261015"}]})

    def test_sweep_keeps_known_companies_and_history_runs_once(self):
        tgts = kr.targets(self.conn, top_n=1)
        client, fake = self.client(self.handler)
        r = kr.collect_disclosures(self.conn, client, tgts, TODAY)
        self.assertEqual(r["swept"], 4)
        self.assertEqual(r["history_companies"], 3)
        self.assertEqual(r["inserted"], 2 + 3)   # 전 시장 2건(상장사만) + 대상 3곳 이력
        self.assertNotIn("status", r)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM disclosures WHERE corp_code='99999999'").fetchone()[0], 0)

        client2, fake2 = self.client(self.handler)
        r2 = kr.collect_disclosures(self.conn, client2, tgts, TODAY)
        self.assertEqual(r2["inserted"], 0)                      # rcp_no 멱등
        self.assertFalse(any("corp_code" in p for _, p in fake2.calls))   # 이력은 다시 받지 않는다

    def test_history_interrupted_by_budget_is_retried_next_run(self):
        tgts = kr.targets(self.conn, top_n=1)
        client, _ = self.client(self.handler, budget=4)   # 전 시장 3콜 + 이력 1콜
        r = kr.collect_disclosures(self.conn, client, tgts, TODAY)
        self.assertEqual(r["budget_exhausted"], 1)
        self.assertEqual(r["history_companies"], 1)
        client2, fake2 = self.client(self.handler)
        r2 = kr.collect_disclosures(self.conn, client2, tgts, TODAY)
        self.assertEqual(r2["history_companies"], 2)


class CompanyTests(DbCase):
    def zip_payload(self, rows):
        xml = "<result>" + "".join(
            f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name><stock_code>{s}</stock_code></list>"
            for c, n, s in rows) + "</result>"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("CORPCODE.xml", xml)
        return buf.getvalue()

    def test_new_listing_and_rename_are_applied(self):
        rows = [("00000001", "보유사", "000001"), ("00000002", "관심사(새 이름)", "000002"), ("00000009", "신규상장", "000009"),
                ("00000008", "비상장", " ")] + [(f"1{i:07d}", f"채움{i}", f"9{i:05d}") for i in range(kr.MIN_LISTED)]
        client, _ = self.client(lambda e, p: FakeResp(content=self.zip_payload(rows)))
        r = kr.refresh_companies(self.conn, client)
        self.assertEqual(r["changed"], 1)
        self.assertEqual(r["inserted"], 1 + kr.MIN_LISTED)
        self.assertEqual(self.conn.execute("SELECT corp_name FROM companies WHERE stock_code='000009'").fetchone()[0], "신규상장")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM companies WHERE corp_code='00000008'").fetchone())

    def test_truncated_or_error_responses_write_nothing(self):
        client, _ = self.client(lambda e, p: FakeResp(content=self.zip_payload([("00000009", "신규", "000009")])))
        self.assertEqual(kr.refresh_companies(self.conn, client)["status"], "error")
        client, _ = self.client(lambda e, p: FakeResp(content=b"<result><status>020</status></result>"))
        r = kr.refresh_companies(self.conn, client)
        self.assertEqual(r["status"], "error")
        self.assertIn("020", r["reason"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM companies").fetchone()[0], 5)


def integration(per="9.78배", eps="22,292원", bps="86,052원", pbr="2.53배"):
    return {"totalInfos": [{"code": "per", "value": per}, {"code": "eps", "value": eps}, {"code": "pbr", "value": pbr},
                           {"code": "bps", "value": bps}, {"code": "dividendYieldRatio", "value": "0.77%"},
                           {"code": "dividend", "value": "1,668원"}, {"code": "cnsPer", "value": "4.79배"}]}


class ValuationTests(DbCase):
    def test_parse_handles_units_and_missing_values(self):
        v = mv.parse_integration(integration())
        self.assertEqual((v["per"], v["pbr"], v["eps"], v["bps"], v["div_yield"], v["dps"]), (9.78, 2.53, 22292, 86052, 0.77, 1668))
        self.assertAlmostEqual(v["roe"], 25.9, places=1)
        v = mv.parse_integration(integration(per="N/A", eps="-1,200원", bps="-"))
        self.assertIsNone(v["per"])
        self.assertIsNone(v["roe"])

    def test_upserts_on_latest_trading_day_and_skips_when_done(self):
        urls = []
        r = mv.fetch_market_valuation(self.conn, get=lambda u: urls.append(u) or FakeResp(integration()), pause=0)
        self.assertEqual((r["date"], r["stocks"], r["failed"]), ("2026-10-15", 5, 0))
        self.assertNotIn("status", r)
        row = self.conn.execute("SELECT per, pbr, bps FROM fundamentals WHERE stock_code='000003'").fetchone()
        self.assertEqual(tuple(row), (9.78, 2.53, 86052))
        self.assertIn("000003", urls[0])   # 시총 큰 종목부터
        again = mv.fetch_market_valuation(self.conn, get=lambda u: self.fail("다시 부르면 안 된다"), pause=0)
        self.assertEqual(again["skipped"], "already")

    def test_all_failures_are_an_error_not_zero_ok(self):
        def boom(url):
            raise requests.ConnectionError("blocked")
        r = mv.fetch_market_valuation(self.conn, get=boom, pause=0)
        self.assertEqual(r["status"], "error")


class ScriptTests(DbCase):
    def test_one_failing_step_does_not_stop_the_rest_and_exit_code_is_1(self):
        spec = importlib.util.spec_from_file_location(
            "collect_kr_company_data", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "collect_kr_company_data.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ran = []
        with patch("sys.argv", ["x"]), \
                patch.object(kr, "refresh_companies", side_effect=lambda *a: ran.append("c") or {"status": "error", "reason": "x"}), \
                patch.object(kr, "collect_disclosures", side_effect=lambda *a: ran.append("d") or {}), \
                patch.object(kr, "collect_financials", side_effect=lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))), \
                patch.object(mv, "fetch_market_valuation", side_effect=lambda *a: ran.append("v") or {}):
            code = mod.main()
        self.assertEqual(code, 1)
        self.assertEqual(ran, ["c", "d", "v"])
        status = dict(self.conn.execute("SELECT job, status FROM job_runs").fetchall())
        self.assertEqual(status, {"kr_companies": "error", "kr_disclosures": "ok", "kr_financials": "error", "kr_valuation": "ok"})


if __name__ == "__main__":
    unittest.main()

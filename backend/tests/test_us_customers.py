"""SEC XBRL 인스턴스 고객 집중도 파싱 — 고객 축·기준·유형 필터, 기간 종류, 사업부 차원 중복 처리 (네트워크 없음)."""
import unittest

from pipeline.us_customers import parse_instance


def _ctx(cid, dims, start=None, end=None, instant=None):
    seg = "".join(f'<xbrldi:explicitMember dimension="{d}">{m}</xbrldi:explicitMember>' for d, m in dims)
    seg = f"<segment>{seg}</segment>" if seg else ""
    per = f"<instant>{instant}</instant>" if instant else f"<startDate>{start}</startDate><endDate>{end}</endDate>"
    return (f'<context id="{cid}"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier>{seg}</entity>'
            f"<period>{per}</period></context>")


def _fact(cid, v, tag="us-gaap:ConcentrationRiskPercentage1"):
    return f'<{tag} contextRef="{cid}" decimals="2" unitRef="number">{v}</{tag}>'


def _doc(*parts):
    return ('<?xml version="1.0" encoding="utf-8"?><xbrl xmlns="http://www.xbrl.org/2003/instance" '
            'xmlns:us-gaap="http://fasb.org/us-gaap/2026" xmlns:srt="http://fasb.org/srt/2026" '
            'xmlns:nvda="http://www.nvidia.com/20260726" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">' + "".join(parts) + "</xbrl>")


CUST = "srt:MajorCustomersAxis"
BENCH = "us-gaap:ConcentrationRiskByBenchmarkAxis"
TYPE = "us-gaap:ConcentrationRiskByTypeAxis"
CCR = "us-gaap:CustomerConcentrationRiskMember"
Q = dict(start="2026-04-27", end="2026-07-26")


class ParseInstanceTest(unittest.TestCase):
    def test_revenue_quarter(self):
        rows = parse_instance(_doc(
            _ctx("c1", [(CUST, "nvda:CustomerAMember"), (BENCH, "us-gaap:SalesRevenueNetMember"), (TYPE, CCR)], **Q),
            _fact("c1", "0.22")))
        self.assertEqual(rows, [{"period_end": "2026-07-26", "period_kind": "Q", "customer": "CustomerA",
                                 "benchmark": "revenue", "pct": 22.0, "extra_dims": None}])

    def test_benchmark_variants_and_receivables(self):
        rows = parse_instance(_doc(
            _ctx("c1", [(CUST, "x:Customer1Member"), (BENCH, "us-gaap:RevenueFromContractWithCustomerProductAndServiceBenchmarkMember")],
                 start="2025-01-27", end="2026-01-25"),
            _ctx("c2", [(CUST, "x:Customer1Member"), (BENCH, "us-gaap:AccountsReceivableMember"), (TYPE, CCR)], instant="2026-01-25"),
            _fact("c1", "0.15"), _fact("c2", "0.3")))
        got = {(r["benchmark"], r["period_kind"], r["pct"]) for r in rows}
        self.assertEqual(got, {("revenue", "FY", 15.0), ("receivables", "I", 30.0)})

    def test_ytd_kind(self):
        rows = parse_instance(_doc(
            _ctx("c1", [(CUST, "x:CustomerBMember"), (BENCH, "us-gaap:RevenueFromContractWithCustomerMember")],
                 start="2026-01-26", end="2026-07-26"),
            _fact("c1", "0.12")))
        self.assertEqual(rows[0]["period_kind"], "YTD")

    def test_skips_non_customer_rows(self):
        rows = parse_instance(_doc(
            # 고객 축 없음(지역 집중도)
            _ctx("g", [("srt:StatementGeographicalAxis", "us-gaap:NonUsMember"), (BENCH, "us-gaap:SalesRevenueNetMember"), (TYPE, CCR)], **Q),
            # 공급자 집중도
            _ctx("s", [(CUST, "x:VendorAMember"), (BENCH, "us-gaap:CostOfGoodsTotalMember"),
                       (TYPE, "us-gaap:SupplierConcentrationRiskMember")], **Q),
            # 기준 축 없음 — 매출인지 채권인지 모름
            _ctx("n", [(CUST, "x:CustomerCMember")], **Q),
            # 차원 없는 값 · 다른 계정
            _ctx("plain", [], **Q),
            _fact("g", "0.38"), _fact("s", "0.4"), _fact("n", "0.2"), _fact("plain", "0.1"),
            _fact("c9", "0.5"), '<us-gaap:Revenues contextRef="plain" unitRef="usd" decimals="-6">100</us-gaap:Revenues>'))
        self.assertEqual(rows, [])

    def test_geographic_location_share_dropped(self):
        rows = parse_instance(_doc(
            _ctx("c1", [(CUST, "nvda:UnitedStatesAndEuropeBasedEndCustomersMember"), (BENCH, "us-gaap:SalesRevenueNetMember"),
                        (TYPE, CCR), ("srt:StatementGeographicalAxis", "country:TW")], start="2025-01-27", end="2026-01-25"),
            _fact("c1", "0.76")))
        self.assertEqual(rows, [])

    def test_out_of_range_value_dropped(self):
        rows = parse_instance(_doc(
            _ctx("c1", [(CUST, "x:CustomerAMember"), (BENCH, "us-gaap:SalesRevenueNetMember")], **Q), _fact("c1", "12")))
        self.assertEqual(rows, [])

    def test_segment_dim_kept_and_fewest_extra_dims_wins(self):
        seg = ("us-gaap:StatementBusinessSegmentsAxis", "nvda:ComputeAndNetworkingMember")
        base = [(CUST, "nvda:RevenueCustomer1Member"), (BENCH, "us-gaap:SalesRevenueNetMember"), (TYPE, CCR)]
        only_seg = parse_instance(_doc(_ctx("a", base + [seg], **Q), _fact("a", "0.16")))
        self.assertEqual(only_seg[0]["extra_dims"], "StatementBusinessSegmentsAxis=ComputeAndNetworkingMember")
        self.assertEqual(only_seg[0]["customer"], "RevenueCustomer1")
        both = parse_instance(_doc(_ctx("a", base + [seg], **Q), _ctx("b", base, **Q), _fact("a", "0.40"), _fact("b", "0.16")))
        self.assertEqual(len(both), 1)
        self.assertEqual((both[0]["pct"], both[0]["extra_dims"]), (16.0, None))




class LabelTest(unittest.TestCase):
    def test_anonymous_and_named(self):
        from pipeline.us_customers import _label
        for anon in ("CustomerA", "RevenueCustomer5", "MajorCustomerOne", "CustomerTwo", "UndisclosedCustomer", "LargestCustomer"):
            self.assertIsNone(_label(anon), anon)
        self.assertEqual(_label("CiscoSystemsInc"), "Cisco Systems Inc")
        self.assertEqual(_label("DellInc"), "Dell Inc")

    def test_group_rows_excluded(self):
        import sqlite3
        from pipeline.us_customers import latest
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE us_customer_concentration (ticker, period_end, period_kind, customer, benchmark, pct)")
        conn.executemany("INSERT INTO us_customer_concentration VALUES ('INTC','2025-12-27','FY',?, 'revenue', ?)",
                         [("ThreeLargestCustomers", 43.0), ("DellInc", 19.0), ("HPInc", 12.0)])
        r = latest(conn, "INTC")
        self.assertEqual([c["pct"] for c in r["customers"]], [19.0, 12.0])


if __name__ == "__main__":
    unittest.main()

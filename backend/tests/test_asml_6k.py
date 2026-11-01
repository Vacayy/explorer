"""ASML 6-K 실적 보도자료 파싱 — 연대별 형식(문장형 2010, 세로표 2013·2016, 가로표 2020·2025, 순수주 공시 중단 2026)."""
import unittest

from pipeline.asml_6k import _expected_quarter, parse_press_release

PR_2010 = """ASML announces 2010 Third Quarter Results
VELDHOVEN, the Netherlands, Oct 13, 2010 — ASML Holding NV (ASML) today announces 2010 third
quarter results according to US GAAP as follows:
•
Q3 2010 net sales of EUR 1,176 million versus Q2 2010 net sales of EUR 1,069 million
(Q3 2009 net sales of EUR 555 million).
•
Q3 2010 net bookings valued at EUR 1,297 million, with 60 systems including 42 new and
18 used systems, leading to a systems backlog valued at EUR 2,693 million as of Sept 26,
"""

# 2013: 현재 분기가 먼저 오는 세로표 + 순수주는 EUV 제외로만 공시
PR_2013 = """VELDHOVEN, the Netherlands, 16 October 2013 - ASML Holding N.V. (ASML) today publishes 2013 third-quarter results.
•
ASML guides fourth-quarter net sales at around EUR 1.8 billion
(Figures in millions of euros unless otherwise indicated)
Q3 2013
Q2 2013
Net sales
1,318
1,187
of which service and field option sales
359
271
Net bookings, excluding EUV
1,415
1,065
Net bookings, excluding EUV (units)
51
38
"""

PR_2016 = """VELDHOVEN, the Netherlands, October 19, 2016 - ASML Holding N.V. (ASML) today publishes its 2016 third-quarter results.
•
Q3 net sales of EUR 1.81 billion , gross margin 46.0 percent
•
ASML guides Q4 2016 net sales between EUR 1.7 and 1.8 billion
(Figures in millions of euros unless otherwise indicated)
Q2 2016
Q3 2016
Net sales
1,740
1,815
...of which service and field option sales
486
577
Net bookings
1,566
1,415
"""

PR_2025 = """VELDHOVEN, the Netherlands, October 15, 2025 – Today, ASML Holding NV (ASML) has published its 2025 third-quarter results.
• Q3 total net sales of €7.5 billion, gross margin of 51.6%, net income of €2.1 billion
• Quarterly net bookings in Q3 of €5.4 billion 2 of which €3.6 billion is EUV
• ASML expects Q4 2025 total net sales between €9.2 billion and €9.8 billion
(Figures in millions of euros unless otherwise indicated) | Q2 2025 | | Q3 2025 | | FY 2024 | | YTD 2025
Total net sales
7,692 | | 7,516 | | 28,263 | | 22,950
...of which Installed Base Management sales 1
2,060 | | 1,956 | | 6,494 | | 6,030
Net bookings 2
5,541 | | 5,399 | | 18,899 | 3
16,378 | 3
Gross profit | 4,134 | | 3,878 | | 14,492 | | 12,111
"""

PR_2026 = """VELDHOVEN, the Netherlands, April 15, 2026 – Today, ASML Holding NV (ASML) has published its 2026 first-quarter results.
• Q1 total net sales of €8.8 billion, gross margin of 53.0%, net income of €2.8 billion
• ASML expects Q2 2026 total net sales between €8.4 billion and €9.0 billion
(Figures in millions of euros unless otherwise indicated) | Q4 2025 | | Q1 2026
Total net sales
9,718 | | 8,767
...of which Installed Base Management sales 1
2,134 | | 2,488
Gross profit | 5,068 | | 4,645
"""


class ParsePressReleaseTests(unittest.TestCase):
    def test_2010_prose_only(self):
        r = parse_press_release(PR_2010)
        self.assertEqual(r["quarter"], "2010-09")
        self.assertEqual(r["net_sales_eur"], 1_176e6)
        self.assertEqual(r["bookings_eur"], 1_297e6)
        self.assertIsNone(r["bookings_scope"])

    def test_2013_current_quarter_first_column_and_excl_euv(self):
        r = parse_press_release(PR_2013)
        self.assertEqual(r["quarter"], "2013-09")
        self.assertEqual(r["net_sales_eur"], 1_318e6)     # 표의 첫 열(현재 분기), 가이던스 1.8bn이 아님
        self.assertEqual(r["bookings_eur"], 1_415e6)
        self.assertEqual(r["bookings_scope"], "excl_euv")

    def test_2016_vertical_table_reported_quarter_not_prior_or_guidance(self):
        r = parse_press_release(PR_2016)
        self.assertEqual(r["quarter"], "2016-09")
        self.assertEqual(r["net_sales_eur"], 1_815e6)
        self.assertEqual(r["bookings_eur"], 1_415e6)

    def test_2025_horizontal_table_with_fy_columns_and_footnotes(self):
        r = parse_press_release(PR_2025)
        self.assertEqual(r["quarter"], "2025-09")
        self.assertEqual(r["net_sales_eur"], 7_516e6)
        self.assertEqual(r["bookings_eur"], 5_399e6)

    def test_2026_bookings_no_longer_disclosed_is_none_not_zero(self):
        r = parse_press_release(PR_2026)
        self.assertEqual(r["quarter"], "2026-03")
        self.assertEqual(r["net_sales_eur"], 8_767e6)
        self.assertIsNone(r["bookings_eur"])

    def test_table_and_headline_disagree_drops_value(self):
        broken = PR_2016.replace("1,740\n1,815", "1,815\n1,740")   # 열을 잘못 짚으면 헤드라인(1.81bn)과 어긋난다
        self.assertIsNone(parse_press_release(broken)["net_sales_eur"])

    def test_not_a_results_release(self):
        r = parse_press_release("ASML Annual General Meeting of Shareholders adopts all resolutions.")
        self.assertEqual(r, {"quarter": None, "net_sales_eur": None, "bookings_eur": None, "bookings_scope": None, "comparatives": {}})

    def test_comparative_columns(self):
        self.assertEqual(parse_press_release(PR_2025)["comparatives"], {"2025-06": 7_692e6})   # FY·YTD 열은 제외
        self.assertEqual(parse_press_release(PR_2013)["comparatives"], {"2013-06": 1_187e6})


class HeaderVariantTests(unittest.TestCase):
    def test_period_footnote_nospace_fy_and_notes_column(self):
        pr_2018 = ("VELDHOVEN, April 18, 2018 - ASML Holding N.V. (ASML) has published its Q1 2018 results.\n"
                   "(Figures in millions of euros unless otherwise indicated)\nQ4 2017 1\nQ1 2018\nNet sales\n2,561\n2,285\n"
                   "...of which Installed Base Management sales 2\n556\n598\nNet bookings 3\n2,935\n2,442\nGross profit\n")
        r = parse_press_release(pr_2018)
        self.assertEqual((r["quarter"], r["net_sales_eur"], r["bookings_eur"]), ("2018-03", 2_285e6, 2_442e6))
        pr_2014 = ("VELDHOVEN, 22 January 2014 - ASML Holding N.V. (ASML) today publishes 2013 fourth-quarter results.\n"
                   "Q4 2013\nQ3 2013\nFY2013\nFY2012\nNet sales\n1,848\n1,318\n5,245\n4,732\n"
                   "Net bookings, excluding EUV\n1,449\n1,415\n4,644\n3,312\n")
        r = parse_press_release(pr_2014)
        self.assertEqual((r["quarter"], r["net_sales_eur"], r["bookings_eur"], r["bookings_scope"]), ("2013-12", 1_848e6, 1_449e6, "excl_euv"))
        pr_2011 = ("ASML announces 2011 third quarter results\nQ3 2011\nQ2 2011\nNotes\nNet sales\n1,459\n1,529\n"
                   "of which service and field option sales\n181\n175\n")
        self.assertEqual(parse_press_release(pr_2011)["net_sales_eur"], 1_459e6)


class ExpectedQuarterTests(unittest.TestCase):
    def test_filing_month_maps_to_prior_quarter(self):
        self.assertEqual(_expected_quarter("2025-01-29"), "2024-12")
        self.assertEqual(_expected_quarter("2010-10-13"), "2010-09")
        self.assertEqual(_expected_quarter("2026-04-15"), "2026-03")
        self.assertEqual(_expected_quarter("2026-07-15"), "2026-06")


if __name__ == "__main__":
    unittest.main()

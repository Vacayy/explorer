"""exp_research — TrendForce·WSTS 전망 문장 파싱 (네트워크 없음). 문장은 실제 보도자료에서 따왔다."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.exp_research import (claims_from_article, extract_claims, norm_period, parse_listing, parse_wsts_prose,  # noqa: E402
                                   parse_wsts_table, subject_node)

SEP30, JUL21, AUG25 = date(2026, 9, 30), date(2026, 7, 21), date(2026, 8, 25)


def one(sentence, published, **kw):
    out = extract_claims(sentence, published, **kw)
    assert len(out) == 1, out
    return out[0]


class ExtractTest(unittest.TestCase):
    def test_range_qoq_quarter(self):
        out = extract_claims("Conventional DRAM contract prices are projected to grow 10–15% QoQ in 4Q26, while NAND Flash contract "
                             "prices are expected to increase 15–20%", SEP30)
        got = {(c["subject"], c["node_key"], c["metric"], c["target_period"], c["value_low"], c["value_high"]) for c in out}
        self.assertEqual(got, {("Conventional DRAM", "memory", "price_qoq", "2026Q4", 10, 15),
                               ("NAND Flash", "memory", "price_qoq", "2026Q4", 15, 20)})

    def test_hyphen_and_to_ranges(self):
        c = one("Long-Term Agreements Cap Price Increases; Server DRAM Contract Prices Expected to Rise 13-18% QoQ in 3Q26", date(2026, 7, 9))
        self.assertEqual((c["subject"], c["value_low"], c["value_high"], c["target_period"]), ("Server DRAM", 13, 18, "2026Q3"))
        c = one("For high-end MLCC products, average hikes are expected to range from 10% to 20% in 4Q26.", date(2026, 8, 27))
        self.assertEqual((c["node_key"], c["metric"], c["value_low"], c["value_high"]), ("mlcc", "growth_qoq", 10, 20))

    def test_single_value_yoy(self):
        c = one("TrendForce now forecasts AI server shipments to grow 32.2% YoY in 2026 given the strong overall demand outlook.",
                date(2026, 10, 14))
        self.assertEqual((c["node_key"], c["metric"], c["target_period"], c["value_low"], c["direction"]),
                         ("ai_odm", "shipments_yoy", "2026", 32.2, "up"))

    def test_decline_is_negative(self):
        c = one("TrendForce forecasts global smartphone production to decline 15–20% YoY in 2026.", JUL21)
        self.assertEqual((c["node_key"], c["metric"], c["value_low"], c["value_high"], c["direction"]),
                         ("mobile_asm", "production_yoy", -20, -15, "down"))

    def test_revision_keeps_new_value(self):
        c = one("TrendForce has therefore revised its 2026 AI server shipment forecast upward from 28% to nearly 31% YoY.", date(2026, 8, 3))
        self.assertEqual((c["value_low"], c["value_high"]), (31, 31))
        c = one("Similarly, NAND Flash contract prices are now expected to rise from 33–38% to 55–60%.", date(2026, 2, 2),
                default_period="2026Q1")
        self.assertEqual((c["value_low"], c["value_high"], c["target_period"]), (55, 60, "2026Q1"))

    def test_past_and_future_in_one_sentence(self):
        out = extract_claims("Server DRAM—a key procurement category for CSPs—saw contract prices rise by a cumulative 64% in 2H25, "
                             "with a further jump of approximately 270% expected in 2026.", AUG25)
        self.assertEqual([(c["node_key"], c["target_period"], c["value_low"]) for c in out], [("memory", "2026", 270)])

    def test_historical_sentences_skipped(self):
        st = {}
        for s in ("Global smartphone production reached 275 million units in 2Q26, down 8% YoY, according to TrendForce’s latest research.",
                  "TrendForce notes that NOR Flash contract prices rose by a cumulative average of 100–120% in the first half of 2026.",
                  "Average contract prices are estimated to have increased by 100–120% during 1H26, with higher-capacity products seeing even stronger gains.",
                  "TrendForce forecasts global server shipments to grow faster in 2027 than the 17% YoY recorded in 2026.",
                  "Its 2Q26 revenue increased 37.9% QoQ to $38.59 billion, while market share edged down to 24.9%."):
            self.assertEqual(extract_claims(s, date(2026, 9, 14), stats=st), [], s)
        self.assertGreaterEqual(st.get("historical", 0) + st.get("not_forecast", 0), 4)

    def test_levels_and_shares_skipped(self):
        for s in ("TrendForce expects OLED monitor penetration to rise to 6.2% by 2030 and continue expanding thereafter.",
                  "AI servers will be the primary driver of this growth, accounting for an estimated 33.4% of total demand capacity.",
                  "TrendForce estimates the DRAM sufficiency ratio at approximately -1% to -2% in 2026."):
            self.assertEqual(extract_claims(s, SEP30), [], s)

    def test_period_fallbacks(self):
        # 기간이 문장에 없으면 바로 앞 문장 → 기사 제목 기간
        c = one("However, the pace of contract price increases is expected to moderate, with conventional DRAM prices projected to rise 10–15% QoQ.",
                SEP30, context=["DRAM suppliers continue to prioritize advanced-process capacity in 4Q26, keeping the market undersupplied."])
        self.assertEqual(c["target_period"], "2026Q4")
        c = one("High-density NOR Flash products are expected to see prices potentially rising by another 60–65% or more in the second half of the year.",
                date(2026, 6, 16))
        self.assertEqual((c["node_key"], c["metric"], c["target_period"]), ("tw_memory", "price_hoh", "2026H2"))
        self.assertEqual(extract_claims("NAND Flash contract prices are projected to increase by 10–15% QoQ.", SEP30), [])

    def test_unknown_subject_kept_without_node(self):
        c = one("TrendForce forecasts global AR glasses shipments to surge from 620,000 units in 2025 to 1.31 million units in 2026, "
                "marking 111.1% YoY growth.", date(2026, 10, 15))
        self.assertEqual((c["subject"], c["node_key"], c["value_low"]), ("global AR glasses shipments", None, 111.1))


class MappingTest(unittest.TestCase):
    def test_subject_node(self):
        cases = {"HBM contract prices": "memory", "server DRAM": "memory", "PC DRAM prices": "memory", "enterprise SSD": "memory",
                 "DDR4 contract prices": "tw_memory", "NOR Flash": "tw_memory", "consumer DRAM": "tw_memory",
                 "foundry revenue": "foundry", "AI server shipments": "ai_odm", "notebook shipments": "nb_odm",
                 "smartphone production": "mobile_asm", "smartphone panel shipments": "display", "MLCC prices": "mlcc",
                 "TV panel prices": "display", "ABF substrates": "abf", "CoWoS capacity": "osat", "semiconductor equipment": "dep_etch",
                 "silicon wafer shipments": "wafer", "CSP CapEx": "ai"}
        for text, node in cases.items():
            self.assertEqual(subject_node(text)[1], node, text)
        self.assertIsNone(subject_node("AR glasses"))

    def test_norm_period(self):
        self.assertEqual(norm_period("4Q26"), "2026Q4")
        self.assertEqual(norm_period("1Q27"), "2027Q1")
        self.assertEqual(norm_period("2H26"), "2026H2")
        self.assertEqual(norm_period("the second half of 2026"), "2026H2")
        self.assertEqual(norm_period("the fourth quarter of 2026"), "2026Q4")
        self.assertEqual(norm_period("Q3 2026"), "2026Q3")
        self.assertEqual(norm_period("in 2027"), "2027")


class PageTest(unittest.TestCase):
    ARTICLE = """<h1>Press Center</h1><script>{"datePublished": "2026-09-30T14:00:00+08:00"}</script>
    <article class="col-md-8 presscenter"><h1>AI Server Demand Sustains Memory Contract Price Increases in 4Q26, Says TrendForce</h1>
    <ul><li>Conventional DRAM contract prices are projected to grow 10–15% QoQ in 4Q26, while NAND Flash contract prices are expected to increase 15–20%</li></ul>
    <p>Meanwhile, the NAND Flash market is seeing a divergence. Overall NAND Flash contract prices are projected to increase 15–20% QoQ.</p>
    <p>For more information on TrendForce’s semiconductor reports, please visit the Report Page.</p></article>"""

    def test_article(self):
        pub, claims = claims_from_article(self.ARTICLE, "https://x/a.html")
        self.assertEqual(pub, "2026-09-30")
        got = {(c["subject"], c["target_period"], c["value_low"]) for c in claims}
        self.assertEqual(got, {("Overall NAND Flash", "2026Q4", 15), ("Conventional DRAM", "2026Q4", 10), ("NAND Flash", "2026Q4", 15)})

    def test_article_layout_change_fails(self):
        with self.assertRaises(ValueError):
            claims_from_article("<html><body>nothing</body></html>", "https://x/a.html", "2026-09-30")

    def test_listing(self):
        html = ('<a class="title-link" href="/presscenter/news/20261015-13273.html"><strong>A</strong></a>'
                '<a href="/presscenter/news/20261014-13269.html">B</a><a href="/presscenter/news/Semiconductors">C</a>')
        self.assertEqual(parse_listing(html), [("https://www.trendforce.com/presscenter/news/20261015-13273.html", "2026-10-15"),
                                               ("https://www.trendforce.com/presscenter/news/20261014-13269.html", "2026-10-14")])


class WstsTest(unittest.TestCase):
    TABLE = """WSTS Forecast Summary
                                         Amounts in US$M         Year on Year Growth in %
          Spring 2026
                                    2025      2026       2027     2025     2026    2027
Americas                            256,476   543,654    701,439    31.4    112.0      29.0
Total World - $M                    795,640 1,511,248 1,913,683     26.2      89.9     26.6
Discrete Semiconductors              30,728    33,188     35,712     -1.0      8.0      7.6
  Logic                             299,547   411,371    522,820    38.8      37.3     27.1
  Memory                            230,042   803,941 1,062,085     39.0    249.5      32.1
"""
    PROSE = ("Following exceptionally strong results in late 2025 and early 2026, the global semiconductor market is now projected to grow "
             "90 percent in 2026, reaching USD 1.51 trillion.\nLogic is expected to remain another major contributor, growing 37 percent in 2026. "
             "Other product categories are forecast to expand at more moderate rates, reflecting a broader industry growth: Microprocessors 20 percent, "
             "Analog 10 percent, Discrete Semiconductors 8 percent, Sensors and Optoelectronics with 3 percent.\n2027 Outlook: Growth Continues\n"
             "For 2027, WSTS forecasts the global semiconductor market to grow a further 27 percent, reaching approximately USD 1.9 trillion. "
             "Memory is again expected to lead market expansion with projected growth of 32 percent, while Logic is forecast to increase by 27 percent.")

    def test_table(self):
        t = parse_wsts_table(self.TABLE)
        self.assertEqual(t[("Memory", "2027")][0], 32.1)
        self.assertEqual(t[("Total World", "2026")][0], 89.9)
        self.assertEqual(t[("Discrete Semiconductors", "2025")][0], -1.0)
        self.assertNotIn(("Americas", "2026"), t)

    def test_prose(self):
        p = {k: v[0] for k, v in parse_wsts_prose(self.PROSE).items()}
        self.assertEqual(p[("Total World", "2026")], 90)
        self.assertEqual(p[("Total World", "2027")], 27)
        self.assertEqual(p[("Logic", "2026")], 37)
        self.assertEqual(p[("Logic", "2027")], 27)
        self.assertEqual(p[("Memory", "2027")], 32)
        self.assertEqual(p[("Micro", "2026")], 20)
        self.assertEqual(p[("Sensors", "2026")], 3)

    def test_prose_layout_change_fails(self):
        with self.assertRaises(ValueError):
            parse_wsts_prose("WSTS released something without numbers.")


if __name__ == "__main__":
    unittest.main()

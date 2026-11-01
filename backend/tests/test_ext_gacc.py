import sqlite3
import unittest
from unittest.mock import patch

from pipeline import ext_gacc
from pipeline.ext_gacc import derive, parse_index, parse_table


def _row(label, unit, *nums, lead=""):
    tds = "".join(f'\t\t\t<td align="right" class="style11">\n\t\t\t\t<span>{n}</span>\n\t\t\t</td>\n' for n in nums)
    return (f"\t\t<tr>\n{lead}\t\t\t<td align=\"left\" class=\"style15\">\n\t\t\t\t<span><b>{label}</b></span>\n\t\t\t</td>\n"
            f"\t\t\t<td align=\"center\" class=\"style18\">\n\t\t\t\t<span><b>{unit}</b></span>\n\t\t\t</td>\n{tds}\t\t</tr>\n")


def _page(title, periods, rows, lead=""):
    head = "".join(f'<td colspan="2" align="center" class="style5"><span><b>{p}</b></span></td>' for p in periods)
    return (f"<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><title>{title}</title></head><body>"
            "<table style=\"border-collapse:collapse;\" class=\"ke-zeroborder\"><tbody>\n"
            f"<tr><td colspan=\"8\" align=\"center\" class=\"style1\"><span><b>{title}</b></span></td></tr>\n"
            "<tr><td colspan=\"8\" align=\"right\" class=\"style2\"><span><b>Unit:US$1,000</b></span></td></tr>\n"
            f"<tr>{lead}<td rowspan=\"2\" class=\"style3\"><span><b>Commodity</b></span></td>"
            "<td rowspan=\"2\" class=\"style4\"><span><b>Quantity<br />\nUnit</b></span></td>"
            f"{head}<td colspan=\"2\" class=\"style5\"><span><b>Percentage Change</b></span></td></tr>\n"
            "<tr><td><span><b>Quantity</b></span></td><td><span><b>Value&nbsp;</b></span></td></tr>\n"
            + "".join(rows) + "</tbody></table></body></html>")


N4, N8 = "&nbsp;" * 4, "&nbsp;" * 8
# 실제 2026-08 페이지(GUID 4b78370a…)에서 대상 행만 남긴 축소본 — 마크업·들여쓰기(&nbsp;) 그대로
AUG_2026 = _page("（14）Major Import Commodities in Quantity and Value,8.2026", ["8", "1to8"], [
    _row(f"{N4}Semiconductor Manufacturing Equipments", "N", "7,021", "4,099,203", "45,539", "25,578,052", "53.6", "27.7"),
    _row(f"{N8}Machinery for manufacturing boules or wafers", "N", "158", "59,509", "1,536", "737,795", "-26.5", "-57.8"),
    _row(f"{N8}Machinery for manufacturing SC devices or IC", "N", "978", "3,264,325", "6,906", "20,387,633", "2.3", "24.0"),
    _row(f"{N8}Electronic integrated circuits", "100MN", "543", "65,823,758", "4,190", "427,665,892", "6.8", "83.7"),
])
# 2018-06 형식: 장비 총계 행 없음, 옛 라벨(&amp;), IC 수량 단위 MN(백만 개)
JUN_2018 = _page("（ 14 ） Major\n  Import Commodities in Quantity and Value,6.2018", ["6", "1to6"], [
    _row("Machines&amp;apparatus for making SC devices and IC", "N", "1,077", "1,366,192", "7,878", "6,078,985", "32.1", "152.7"),
    _row("Electronic integrated circuits", "MN", "34,219", "25,228,425", "195,800", "146,705,453", "2.6", "16.2"),
])
# 2022-02 형식: 행 앞에 빈 칸, 라벨 줄바꿈
LEAD = '\t\t\t<td class="style1">\n\t\t\t\t<br />\n\t\t\t</td>\n'
FEB_2022 = _page("（14）Major Import Commodities in Quantity and Value,2.2022", ["2", "1to2"], [
    _row("Semiconductor Manufacturing Equipments", "N", "1", "2,000", "3", "5,000", "-", "-", lead=LEAD),
    _row("Machinery for\n  manufacturing SC devices or IC", "N", "1", "1,000", "2", "2,500", "-", "-", lead=LEAD),
    _row(f"{N8}Electronic\n  integrated circuits", "100MN", "408", "29,950,222", "920", "68,840,600", "-3.7", "1.0", lead=LEAD),
], lead='<td class="style1"><br /></td>')
# 2026-01 형식: 당월 열만
JAN_2026 = _page("（14）Major Import Commodities in Quantity and Value,1.2026", ["1"], [
    _row("Semiconductor Manufacturing Equipments", "N", "3,988", "2,957,423", "5.6", "-21.1"),
    _row("Machinery for manufacturing SC devices or IC", "N", "809", "2,475,914", "-5.7", "-19.3"),
    _row("Electronic integrated circuits", "100MN", "495", "41,241,450", "18.7", "36.0"),
])
# 누계만 있는 2월(2020-02 '1 to 2' 형식)
FEB_2026_YTD = _page("（14）Major Import Commodities in Quantity and Value,2.2026", ["1 to 2"], [
    _row("Semiconductor Manufacturing Equipments", "N", "7,604", "4,649,218", "-", "-"),
    _row("Machinery for manufacturing SC devices or IC", "N", "1,239", "3,690,091", "-", "-"),
    _row("Electronic integrated circuits", "100MN", "910", "78,223,350", "-", "-"),
])
INDEX = ("<table><thead><tr><th>Title</th><th>Month</th></tr></thead><tbody>"
         "<tr><td>（13）Major Export Commodities in Quantity and Value</td><td><a href=http://x/13a.html> Jan.</a></td></tr>"
         "<tr><td>（14）Major Import Commodities in Quantity and Value</td><td><a href=http://x/jan.html> Jan.</a>"
         "<a href=http://x/feb.html> Feb.</a></br><span>Mar.</span><span>Apr.</span></td></tr></tbody></table>")


class ParseTests(unittest.TestCase):
    def test_parse_real_layout(self):
        p = parse_table(AUG_2026)
        self.assertEqual((p["year"], p["month"]), (2026, 8))
        self.assertEqual(p["rows"]["ic"]["month"], (543.0, 65823758.0))
        self.assertEqual(p["rows"]["ic"]["ytd"], (4190.0, 427665892.0))
        self.assertEqual(p["rows"]["semi_equip"]["month"][1], 4099203.0)
        self.assertEqual(p["rows"]["ic_equip"]["month"][1], 3264325.0)
        self.assertEqual(set(p["rows"]), {"ic", "semi_equip", "ic_equip"})  # boules/wafers 행은 무시

    def test_old_label_alias_and_mn_unit(self):
        p = parse_table(JUN_2018)
        self.assertEqual(p["rows"]["ic_equip"]["month"][1], 1366192.0)
        self.assertAlmostEqual(p["rows"]["ic"]["month"][0], 342.19)  # 34,219 MN → 1억 개
        self.assertNotIn("semi_equip", p["rows"])
        self.assertEqual(ext_gacc.required_rows(2018), ["ic", "ic_equip"])

    def test_leading_blank_cell_and_wrapped_label(self):
        p = parse_table(FEB_2022)
        self.assertEqual(p["rows"]["ic"]["month"], (408.0, 29950222.0))
        self.assertEqual(p["rows"]["ic_equip"]["ytd"], (2.0, 2500.0))

    def test_unknown_qty_unit_raises(self):
        with self.assertRaises(ValueError):
            parse_table(AUG_2026.replace("100MN", "10000N"))

    def test_missing_value_unit_header_raises(self):
        with self.assertRaises(ValueError):
            parse_table(AUG_2026.replace("Unit:US$1,000", "Unit:US$1,000,000"))

    def test_index(self):
        self.assertEqual(parse_index(INDEX), {1: "http://x/jan.html", 2: "http://x/feb.html"})


class DeriveTests(unittest.TestCase):
    def test_ytd_minus_previous_ytd(self):
        pages = {(2026, 1): parse_table(JAN_2026), (2026, 2): parse_table(FEB_2026_YTD)}
        data, notes, gaps = derive(pages)
        self.assertEqual(dict(data["gacc:ic_import_usd"]), {"2026-01": 41241450.0, "2026-02": 36981900.0})
        self.assertEqual(dict(data["gacc:ic_import_qty"])["2026-02"], 415.0)
        self.assertEqual(dict(data["gacc:semi_equip_import_usd"])["2026-02"], 1691795.0)
        self.assertEqual(len(notes), 4)
        self.assertEqual(gaps, [])

    def test_ytd_without_previous_month_is_gap(self):
        data, notes, gaps = derive({(2026, 2): parse_table(FEB_2026_YTD)})
        self.assertEqual(data["gacc:ic_import_usd"], [])
        self.assertEqual(len(gaps), 4)
        self.assertIn("2026-02", gaps[0])


class _Conn:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE ext_series (series TEXT, period TEXT, value REAL, unit TEXT, source TEXT, "
                        "fetched_at TEXT, PRIMARY KEY (series, period))")

    def execute(self, *a):
        return self.db.execute(*a)

    def commit(self):
        self.db.commit()

    def close(self):
        pass


class CollectTests(unittest.TestCase):
    def _run(self, pages):
        conn = _Conn()
        urls = {ext_gacc.INDEX_URL: INDEX, "http://x/jan.html": pages[0], "http://x/feb.html": pages[1]}
        with patch.object(ext_gacc, "_get", side_effect=urls.__getitem__), patch.object(ext_gacc, "RECENT", 2), \
             patch("database.get_connection", return_value=conn):
            return ext_gacc.collect(), conn

    def test_ok(self):
        res, conn = self._run([JAN_2026, FEB_2026_YTD])
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["latest"], "2026-02")
        self.assertEqual(len(res["series"]), 4)
        self.assertEqual(conn.db.execute("SELECT unit FROM ext_series WHERE series='gacc:ic_import_qty'").fetchone()[0],
                         "100 million pieces")

    def test_missing_row_fails_loudly(self):
        broken = FEB_2026_YTD.replace("Machinery for manufacturing SC devices or IC", "Machinery for SC things")
        res, _ = self._run([JAN_2026, broken])
        self.assertEqual(res["status"], "partial")
        self.assertIn("2026-02", res["error"])
        self.assertIn("Machinery for manufacturing SC devices or IC", res["error"])


if __name__ == "__main__":
    unittest.main()

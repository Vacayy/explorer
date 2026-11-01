import unittest

from pipeline.ext_jp_trade import CHAPTERS, SERIES, aggregate, parse_index, parse_listing

# 실제 e-Stat 品別国別表(輸出) 2026년 8월분 16부 CSV(2026-10 확인)에서 행 몇 개만 남김.
# 8월 이후 열은 0, '85XXXXXXA'는 류 단위 비밀 행, 847130000은 대상 밖 품목
CSV = (
    "Exp or Imp,Year,HS,Country,Unit1,Unit2,Quantity1-Year,Quantity2-Year,Value-Year,Quantity1-Jan,Quantity2-Jan,Value-Jan,"
    "Quantity1-Feb,Quantity2-Feb,Value-Feb,Quantity1-Mar,Quantity2-Mar,Value-Mar,Quantity1-Apr,Quantity2-Apr,Value-Apr,"
    "Quantity1-May,Quantity2-May,Value-May,Quantity1-Jun,Quantity2-Jun,Value-Jun,Quantity1-Jul,Quantity2-Jul,Value-Jul,"
    "Quantity1-Aug,Quantity2-Aug,Value-Aug,Quantity1-Sep,Quantity2-Sep,Value-Sep,Quantity1-Oct,Quantity2-Oct,Value-Oct,"
    "Quantity1-Nov,Quantity2-Nov,Value-Nov,Quantity1-Dec,Quantity2-Dec,Value-Dec\n"
    "1,2026,'848620000',103,NO,KG,1248,8652822,448474988,121,956464,57250827,134,871932,45160853,220,1397204,76639071,"
    "154,1081650,54598311,151,1028199,45549195,163,1142344,57229583,150,1023996,52677232,155,1151033,59369916,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'848620000',105,NO,KG,3335,19403674,770270051,268,1471512,48853553,280,1442694,46405416,458,3125726,138142165,"
    "387,1840663,69412085,390,1925196,65598863,517,3064104,112161338,576,3648528,152875396,459,2885251,136821235,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'848620000',106,NO,KG,2277,15534780,568190888,180,1132269,45356782,220,1632329,58608798,439,2925323,98103038,"
    "284,1707000,62183604,283,2017221,74890665,307,2292028,88019725,316,2005346,73427296,248,1823264,67600980,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'848620000',304,NO,KG,826,4124818,168309549,58,161286,6127247,86,380892,19538276,112,486285,20417786,"
    "130,835708,33534020,72,466690,17830779,100,413573,20600991,129,496780,19853139,139,883604,30407311,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'848690000',112,  ,KG,0,960820,44374492,0,88386,4473617,0,147137,5631821,0,145635,4983008,0,135161,6511497,"
    "0,78062,4768492,0,101033,5741427,0,113695,6496418,0,151711,5768212,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'85XXXXXXA',111,  ,KG,0,160291,88645,0,0,0,0,0,0,0,60154,31664,0,0,0,0,0,0,0,0,0,0,100137,56981,"
    "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\n"
    "1,2026,'847130000',105,  ,NO,0,71176,519857,0,5816,46304,0,7342,39461,0,14366,69067,0,5990,93372,0,9734,95208,"
    "0,8749,64445,0,18433,79553,0,746,32447,0,0,0,0,0,0,0,0,0,0,0,0\n"
)
SPECS_84 = {s: v for s, v in SERIES.items() if v[0].startswith("84")}

# 목록 첫 화면(연도별 최신 월 링크)과 연도 화면(파일 항목)의 실제 마크업 축소
INDEX = """
<li class="stat-cycle_header"><span>2026年</span></li>
<a tabindex="22" href="/stat-search/files?page=1&amp;layout=datalist&amp;data=1&amp;metadata=1&amp;cycle=1&amp;toukei=00350300&amp;tstat=000001013141&amp;tclass1=000001013180&amp;tclass2=000001013181&amp;cycle_facet=cycle&amp;tclass3val=0&amp;year=20260&amp;month=23070908&amp;result_back=1" class="stat-item_child">8月</a>
<li class="stat-cycle_header"><span>2025年</span></li>
<a tabindex="22" href="/stat-search/files?page=1&amp;layout=datalist&amp;data=1&amp;metadata=1&amp;cycle=1&amp;toukei=00350300&amp;tstat=000001013141&amp;tclass1=000001013180&amp;tclass2=000001013181&amp;cycle_facet=cycle&amp;tclass3val=0&amp;year=20250&amp;month=24101212&amp;result_back=1" class="stat-item_child">12月</a>
"""


def _item(sid: str, title: str) -> str:
    return f"""
<article class="stat-dataset_list-item">
  <a tabindex="22" href="/stat-search/files?page=1&amp;year=20260&amp;stat_infid={sid}" class="stat-link_text stat-dataset_list-detail-item-text js-data" data-key="uid" data-value="{sid}" data-key1="page" data-value1="1">
                                {title}
                                </a>
  <a href="/stat-search/file-download?statInfId={sid}&fileKind=1" class="stat-dl_icon" data-file_type="CSV"><span class="stat-dl_text">CSV</span></a>
</article>"""


LISTING = "".join([
    _item("000040507855", "2026年8月分 品別国別表 (輸出 1-8月：確報) ５部 25-27類"),
    _item("000040507856", "2026年8月分 品別国別表 (輸出 1-8月：確報) ６部 28-38類"),
    _item("000040507866", "2026年8月分 品別国別表 (輸出 1-8月：確報) １６部 84-85類"),
    _item("000040507868", "2026年8月分 品別国別表 (輸出 1-8月：確報) １８部 90-92類"),
    _item("000040507870", "2026年8月分 品別国別表 (輸出 1-8月：確報) ２１部 97類"),
])


class AggregateTests(unittest.TestCase):
    def test_country_and_all_sums_through_latest_month(self):
        got, codes = aggregate(CSV, 2026, 8, SPECS_84)
        self.assertEqual(len(got["jp_exp:8486:ALL"]), 8)  # 9~12월(0 채움)은 버린다
        self.assertEqual(got["jp_exp:8486:CN"][-1], ("2026-08", 136821235.0))
        self.assertEqual(got["jp_exp:8486:KR"][0], ("2026-01", 57250827.0))
        self.assertEqual(got["jp_exp:8486:TW"][-1], ("2026-08", 67600980.0))
        self.assertEqual(got["jp_exp:8486:US"][-1], ("2026-08", 30407311.0))
        # ALL = 모든 국가(112 포함) 합, 8471·비밀 행 제외
        self.assertEqual(got["jp_exp:8486:ALL"][-1],
                         ("2026-08", 59369916.0 + 136821235 + 67600980 + 30407311 + 5768212))
        self.assertEqual(codes, {"848620000", "848690000"})

    def test_series_without_rows_is_absent(self):
        got, _ = aggregate(CSV, 2026, 8, {"jp_exp:903141:ALL": ("903141", None)})
        self.assertEqual(got, {})

    def test_missing_column_raises(self):
        with self.assertRaises(ValueError):
            aggregate(CSV.replace("Value-Mar", "Val-Mar"), 2026, 8, SPECS_84)

    def test_year_mismatch_raises(self):
        with self.assertRaises(ValueError):
            aggregate(CSV, 2025, 8, SPECS_84)


class ListingTests(unittest.TestCase):
    def test_index_year_links(self):
        years = parse_index(INDEX)
        self.assertEqual(sorted(years), [2025, 2026])
        self.assertIn("year=20260&month=23070908", years[2026])
        self.assertNotIn("&amp;", years[2026])

    def test_listing_maps_chapters_to_statinfid(self):
        files = parse_listing(LISTING)
        self.assertEqual({ch: files[ch] for ch in CHAPTERS}, {
            37: ("000040507856", 2026, 8), 38: ("000040507856", 2026, 8),
            84: ("000040507866", 2026, 8), 90: ("000040507868", 2026, 8)})
        self.assertEqual(files[97][0], "000040507870")

    def test_annual_final_title_without_month(self):
        files = parse_listing(_item("000031907283", "2024年分 品別国別表 (輸出 1-12月：確定) １６部 84-85類"))
        self.assertEqual(files[84], ("000031907283", 2024, 12))
        files = parse_listing(_item("000032000001", "2025年 品別国別表 (輸出 1-12月：確々報) １８部 90-92類"))
        self.assertEqual(files[90], ("000032000001", 2025, 12))

    def test_unparseable_titles_raise(self):
        with self.assertRaises(ValueError):
            parse_listing(LISTING.replace("品別国別表 (輸出", "品別国別表 (EXP"))

    def test_listing_without_download_link_raises(self):
        with self.assertRaises(ValueError):
            parse_listing(LISTING.replace("statInfId=000040507866&fileKind=1", "statInfId=X"))


if __name__ == "__main__":
    unittest.main()

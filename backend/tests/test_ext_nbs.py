import unittest
from unittest import mock

from pipeline import ext_nbs
from pipeline.ext_nbs import fill_jan_feb, find_child, parse_es, pick_indicators

CUR, YTD = "09008937b0f148b7ac12855a9dbf8913", "4f1b8371309d4c25afff8ca3ebaebdfa"


def _v(dp, _id, value):
    name = "集成电路产量当期值 (亿块) " if dp == "1" else "集成电路产量累计值 (亿块) "
    return {"i_showname": name, "dp": dp, "_id": _id, "du_name": "亿块", "value": value, "da": "000000000000"}


# 실제 esData 응답(2026-10 수집, 集成电路)을 축소: 1월 둘 다 빈칸, 2월은 累计值만, 3월부터 정상, 미래 달은 빈칸
ES_DATA = [
    {"code": "202604MM", "name": "2026年4月", "values": [_v("1", CUR, ""), _v("21", YTD, "")]},
    {"code": "202603MM", "name": "2026年3月", "values": [_v("1", CUR, "475.1"), _v("21", YTD, "1271.6")]},
    {"code": "202602MM", "name": "2026年2月", "values": [_v("1", CUR, ""), _v("21", YTD, "815.2")]},
    {"code": "202601MM", "name": "2026年1月", "values": [_v("1", CUR, ""), _v("21", YTD, "")]},
    {"code": "202512MM", "name": "2025年12月", "values": [_v("1", CUR, "480.7"), _v("21", YTD, "4842.8")]},
]
# queryIndicatorsByCid data.list 축소 (증감률 지표 포함)
INDICATORS = [
    {"_id": CUR, "dp": "1", "dp_name": "本期", "i_showname": "集成电路产量当期值 (亿块) ", "du_name": "亿块"},
    {"_id": YTD, "dp": "21", "dp_name": "本期累计", "i_showname": "集成电路产量累计值 (亿块) ", "du_name": "亿块"},
    {"_id": "x11", "dp": "11", "dp_name": "同比增减%", "i_showname": "集成电路产量同比增长 (%) ", "du_name": "%"},
]


class ParseTests(unittest.TestCase):
    def test_pick_indicators(self):
        self.assertEqual(pick_indicators(INDICATORS), (CUR, YTD, "亿块"))
        with self.assertRaises(ValueError):
            pick_indicators(INDICATORS[1:])

    def test_parse_es_skips_blanks(self):
        cur, ytd = parse_es(ES_DATA, CUR, YTD)
        self.assertEqual(cur, {"2026-03": 475.1, "2025-12": 480.7})
        self.assertEqual(ytd, {"2026-03": 1271.6, "2026-02": 815.2, "2025-12": 4842.8})

    def test_find_child_by_name(self):
        items = [{"_id": "a", "name": "铁矿石原矿"}, {"_id": "b", "name": "移动通信手持机（手机）"}]
        self.assertEqual(find_child(items, ext_nbs.PRODUCTS["nbs:mobile_output"][0]), "b")
        self.assertIsNone(find_child(items, ("集成电路",)))


class JanFebTests(unittest.TestCase):
    def test_split_ytd_in_half_when_both_missing(self):
        out, split = fill_jan_feb(*parse_es(ES_DATA, CUR, YTD))
        self.assertAlmostEqual(out["2026-01"], 407.6)
        self.assertAlmostEqual(out["2026-02"], 407.6)
        self.assertEqual(split, ["2026-01", "2026-02"])
        self.assertNotIn("2026-04", out)  # 다른 달은 만들지 않는다

    def test_exact_when_feb_present(self):
        out, split = fill_jan_feb({"2026-02": 400.0}, {"2026-02": 815.2})
        self.assertAlmostEqual(out["2026-01"], 415.2)
        self.assertEqual(out["2026-02"], 400.0)
        self.assertEqual(split, [])

    def test_untouched_when_both_present_or_no_ytd(self):
        cur = {"2026-01": 1.0, "2026-02": 2.0}
        self.assertEqual(fill_jan_feb(cur, {"2026-02": 99.0}), (cur, []))
        self.assertEqual(fill_jan_feb({"2026-03": 5.0}, {}), ({"2026-03": 5.0}, []))


class LoudFailureTests(unittest.TestCase):
    def test_category_not_found_returns_error(self):
        def fake_get(url, params=None, **_):
            r = mock.Mock()
            r.raise_for_status.return_value = None
            if "queryIndexTreeAsync" in url:  # 트리에 해당 이름이 없다
                r.json.return_value = {"success": True, "data": [{"_id": "z", "name": "价格指数"}]}
            else:  # 알려진 ID도 지표가 비어 있다(ID 변경)
                r.json.return_value = {"success": True, "data": {"total": 0, "list": []}}
            return r

        with mock.patch.object(ext_nbs.requests, "get", side_effect=fake_get), \
                mock.patch.object(ext_nbs.requests, "post") as post:
            out = ext_nbs.collect()
        post.assert_not_called()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["stored"], 0)
        self.assertEqual(out["path"], "fallback_ids")
        self.assertIn("카테고리를 찾지 못함", out["error"])


if __name__ == "__main__":
    unittest.main()

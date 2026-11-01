import unittest

from pipeline.ext_comtrade import months_to_fetch, parse_availability, parse_preview

# 실제 preview 응답(2026-10 확인, 일본→중국 HS 8486 2024-06)을 축소 — 쓰는 필드만 남김
PREVIEW = {"elapsedTime": "1.44 secs", "count": 1, "error": "", "data": [{
    "typeCode": "C", "freqCode": "M", "refPeriodId": 20240601, "period": "202406", "reporterCode": 392,
    "flowCode": "X", "partnerCode": 156, "partner2Code": 0, "classificationCode": "H6", "cmdCode": "8486",
    "customsCode": "C00", "motCode": 0, "netWgt": 6248569.0, "cifvalue": None,
    "fobvalue": 1220265437.463, "primaryValue": 1220265437.463, "isReported": False, "isAggregate": True}]}
EMPTY = {"elapsedTime": "0.02 secs", "count": 0, "data": [], "error": ""}
# getDA 응답 축소
DA = {"count": 3, "data": [{"period": 202607, "reporterCode": 392, "classificationCode": "H6"},
                           {"period": 201812, "reporterCode": 392, "classificationCode": "H5"},
                           {"period": 202608, "reporterCode": 392, "classificationCode": "H6"}]}


def _months(a: str, b: str) -> list[str]:
    out, (y, m) = [], (int(a[:4]), int(a[5:]))
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class ParseTests(unittest.TestCase):
    def test_preview_fob_value(self):
        self.assertEqual(parse_preview(PREVIEW), 1220265437.463)

    def test_primary_value_fallback_when_no_fob(self):
        rec = dict(PREVIEW["data"][0], fobvalue=None, primaryValue=5.0)
        self.assertEqual(parse_preview({"data": [rec], "error": ""}), 5.0)

    def test_empty_month_is_none_not_zero(self):
        self.assertIsNone(parse_preview(EMPTY))

    def test_non_aggregate_rows_ignored(self):
        other = dict(PREVIEW["data"][0], motCode=1000, fobvalue=1.0)  # 운송수단별 분해 행
        self.assertEqual(parse_preview({"data": [PREVIEW["data"][0], other], "error": ""}), 1220265437.463)

    def test_duplicate_aggregate_raises(self):
        with self.assertRaises(ValueError):
            parse_preview({"data": [PREVIEW["data"][0]] * 2, "error": ""})

    def test_api_error_raises(self):
        with self.assertRaises(ValueError):
            parse_preview({"data": [], "error": "bad request"})

    def test_availability_sorted_ym(self):
        self.assertEqual(parse_availability(DA), ["2018-12", "2026-07", "2026-08"])


class MonthsToFetchTests(unittest.TestCase):
    AVAIL = _months("2010-01", "2026-08")

    def test_backfill_from_2019(self):
        got = months_to_fetch(self.AVAIL, set(), backfill=True)
        self.assertEqual((got[0], got[-1], len(got)), ("2019-01", "2026-08", 92))

    def test_daily_recent_four_when_complete(self):
        stored = set(_months("2019-01", "2026-07"))
        self.assertEqual(months_to_fetch(self.AVAIL, stored, backfill=False),
                         ["2026-05", "2026-06", "2026-07", "2026-08"])

    def test_daily_resumes_unstored_months(self):
        stored = set(_months("2019-01", "2026-08")) - {"2020-03", "2021-11"}  # 중단·빈 월
        self.assertEqual(months_to_fetch(self.AVAIL, stored, backfill=False),
                         ["2020-03", "2021-11", "2026-05", "2026-06", "2026-07", "2026-08"])

    def test_availability_gap_not_requested(self):
        avail = [p for p in self.AVAIL if p != "2026-06"]  # 보고국이 아직 발표 안 한 월
        stored = set(_months("2019-01", "2026-08"))
        self.assertEqual(months_to_fetch(avail, stored, backfill=False),
                         ["2026-04", "2026-05", "2026-07", "2026-08"])


if __name__ == "__main__":
    unittest.main()

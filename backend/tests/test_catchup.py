"""정기 작업 따라잡기 판정 — 회차 성공이면 건너뛰고, 실패·누락이면 간격을 늘려 다시, 늦으면 포기 (D-249)."""
import unittest
from datetime import datetime, timedelta, timezone

from pipeline.catchup import MAX_ATTEMPTS, decide, last_due

KST = timezone(timedelta(hours=9))
WEEKDAYS_1635_2020 = [{"Weekday": d, "Hour": h, "Minute": m} for d in range(1, 6) for h, m in ((16, 35), (20, 20))]


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=KST)


class LastDueTests(unittest.TestCase):
    def test_latest_slot_today(self):
        self.assertEqual(last_due(WEEKDAYS_1635_2020, at("2026-10-16 21:00")), at("2026-10-16 20:20"))   # 금

    def test_weekend_points_back_to_friday(self):
        self.assertEqual(last_due(WEEKDAYS_1635_2020, at("2026-10-18 10:00")), at("2026-10-16 20:20"))   # 일

    def test_daily_dict_before_time_is_yesterday(self):
        self.assertEqual(last_due({"Hour": 6, "Minute": 30}, at("2026-10-17 05:00")), at("2026-10-16 06:30"))

    def test_weekly_sunday(self):
        self.assertEqual(last_due({"Weekday": 0, "Hour": 6, "Minute": 0}, at("2026-10-17 12:00")), at("2026-10-11 06:00"))


class DecideTests(unittest.TestCase):
    due = at("2026-10-17 06:30")

    def test_success_after_due_skips(self):
        run, why = decide(self.due, [("ok", at("2026-10-17 06:31"))], at("2026-10-17 12:00"))
        self.assertFalse(run)
        self.assertIn("이미 성공", why)

    def test_success_before_due_does_not_count(self):
        run, _ = decide(self.due, [("ok", at("2026-10-16 06:31"))], at("2026-10-17 12:00"))
        self.assertTrue(run)

    def test_failed_attempt_waits_growing_gap(self):
        runs = [("error", at("2026-10-17 10:36"))]
        self.assertFalse(decide(self.due, runs, at("2026-10-17 10:50"))[0])     # 30분 안
        self.assertTrue(decide(self.due, runs, at("2026-10-17 11:10"))[0])
        runs.append(("error", at("2026-10-17 11:10")))
        self.assertFalse(decide(self.due, runs, at("2026-10-17 12:00"))[0])     # 두 번째 뒤엔 60분
        self.assertTrue(decide(self.due, runs, at("2026-10-17 12:15"))[0])

    def test_gives_up_after_max_attempts(self):
        runs = [("error", at("2026-10-17 07:00") + timedelta(hours=i)) for i in range(MAX_ATTEMPTS)]
        run, why = decide(self.due, runs, at("2026-10-18 06:00"))
        self.assertFalse(run)
        self.assertIn("멈춤", why)

    def test_window_limits_late_catchup(self):
        self.assertFalse(decide(at("2026-10-17 07:00"), [], at("2026-10-17 13:00"), window_h=5)[0])
        self.assertTrue(decide(at("2026-10-17 07:00"), [], at("2026-10-17 11:00"), window_h=5)[0])

    def test_skipped_counts_as_done(self):
        self.assertFalse(decide(self.due, [("skipped", at("2026-10-17 06:31"))], at("2026-10-17 12:00"))[0])


if __name__ == "__main__":
    unittest.main()

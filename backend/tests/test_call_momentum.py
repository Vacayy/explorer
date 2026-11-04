"""실적 발언 모멘텀 (transcript-momentum, D-217). 가짜 문서·가짜 LLM."""
import json
import sqlite3
import unittest

from pipeline import call_momentum as cm
from pipeline import sec_filings as sec


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(cm.SCHEMA + sec.SCHEMA + """
        CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT, title TEXT, markdown TEXT);
        CREATE TABLE transcripts (raw_doc_id INT, ticker TEXT, call_date TEXT);
        CREATE TABLE transcript_follow (ticker TEXT, company_name TEXT, entity_id INT, active INT, fiscal_year_end TEXT);
        CREATE TABLE signals (signal_type TEXT, entity_id INT, date TEXT, payload_json TEXT, UNIQUE(signal_type, entity_id, date));
        INSERT INTO transcript_follow VALUES ('ACME','Acme',7,1,NULL);
    """)
    return c


def add_release(c, doc_id, day, text, title="Acme (ACME) 실적 보도자료"):
    c.execute("INSERT INTO raw_documents VALUES (?,?,?,?)", (doc_id, "earnings_release", title, text))
    c.execute("INSERT INTO earnings_releases (doc_id, ticker, accession, filing_date, exhibit_type) VALUES (?,?,?,?,?)",
              (doc_id, "ACME", f"a{doc_id}", day, "EX-99.1"))


class MomentumTests(unittest.TestCase):
    def test_verify_drops_invented_quotes(self):
        p = cm.verify({"drivers": [{"name": "x", "quote": "Data center revenue grew 40% sequentially"},
                                   {"name": "y", "quote": "We see unprecedented demand for widgets"}]},
                      "Highlights: Data Center revenue grew 40% sequentially, driven by Blackwell.")
        self.assertEqual([d["verified"] for d in p["drivers"]], [True, False])

    def test_events_attach_transcript_within_window(self):
        c = db()
        add_release(c, 1, "2026-02-20", "q4")
        add_release(c, 2, "2026-05-20", "q1")
        c.execute("INSERT INTO raw_documents VALUES (3,'transcript','call','text')")
        c.execute("INSERT INTO transcripts VALUES (3,'ACME','2026-05-21')")
        ev = cm.events(c, "ACME")
        self.assertEqual([e["date"] for e in ev], ["2026-02-20", "2026-05-20"])
        self.assertEqual(sorted(d["doc_id"] for d in ev[1]["docs"]), [2, 3])

    def test_pipeline_flags_new_driver_with_prior_context(self):
        c = db()
        add_release(c, 1, "2026-02-20", "Cloud revenue grew steadily this quarter. Demand remained healthy across regions.")
        add_release(c, 2, "2026-05-20", "Cloud revenue grew steadily this quarter. Our new AI inference platform contributed $200 million "
                                        "in its first full quarter. We raised full year revenue outlook to $10 billion.")
        prompts = []

        def fake(prompt):
            prompts.append(prompt)
            if "AI inference platform" in prompt:
                return json.dumps({"drivers": [
                    {"name": "AI inference platform", "type": "product", "status": "new", "magnitude": "$200M",
                     "quote": "Our new AI inference platform contributed $200 million"},
                    {"name": "Cloud", "type": "segment", "status": "steady", "quote": "Cloud revenue grew steadily this quarter"}],
                    "guidance": [{"metric": "FY revenue", "direction": "raised", "quote": "We raised full year revenue outlook to $10 billion"}],
                    "demand_tone": 4, "qa_focus": []})
            return json.dumps({"drivers": [{"name": "Cloud", "type": "segment", "status": "steady",
                                            "quote": "Cloud revenue grew steadily this quarter"}], "guidance": [], "demand_tone": 3})
        self.assertEqual(cm.extract_pending(c, call=fake)["extracted"], 2)
        self.assertIn("(없음)", prompts[0])                  # 첫 발표는 직전 동인 없음
        self.assertIn("- Cloud", prompts[1])                 # 두 번째는 직전 동인을 받는다
        self.assertEqual(cm.judge(c)["new_candidates"], 1)
        rows = {r["event_date"]: (r["status"], r["score"]) for r in c.execute("SELECT * FROM call_momentum")}
        self.assertEqual(rows["2026-02-20"][0], "first")
        self.assertEqual(rows["2026-05-20"], ("candidate", 6.0))   # 가이던스 상향 3 + 어조 +1단계 2 + 새 동인 1 = 6 (매출 재료 없음 → 가속 판정 없음)
        self.assertEqual(c.execute("SELECT count(*) FROM signals WHERE signal_type='call_momentum'").fetchone()[0], 1)
        self.assertEqual(cm.judge(c)["new_candidates"], 0)         # 다시 돌려도 새 후보로 세지 않음
        # AI 핵심 요약 — 이번 시즌 후보만, 근거가 같으면 다시 쓰지 않고, 매일 판정해도 지워지지 않는다
        from datetime import date
        asked = []
        summ = lambda p: asked.append(p) or "AI 추론 플랫폼이 새 동인으로 등장했다."  # noqa: E731
        self.assertEqual(cm.summarize(c, call=summ, today=date(2026, 5, 25))["summarized"], 1)
        self.assertIn("Our new AI inference platform contributed $200 million", asked[0])
        self.assertIn("가이던스 상향", asked[0])
        self.assertEqual(cm.summarize(c, call=summ, today=date(2026, 5, 25))["unchanged"], 1)
        cm.judge(c)
        self.assertEqual(c.execute("SELECT summary FROM call_momentum WHERE status='candidate'").fetchone()[0], "AI 추론 플랫폼이 새 동인으로 등장했다.")
        self.assertEqual(cm.summarize(c, call=summ, today=date(2026, 8, 1))["summarized"], 0)   # 지난 시즌 후보는 요약하지 않는다
        self.assertEqual(cm.weekly_message(c)[0], [])              # 옛 실적 발표(백필)는 주간 알림에 안 나간다
        c.execute("UPDATE call_momentum SET event_date=date('now','-3 day') WHERE status='candidate'")
        items, _ = cm.weekly_message(c)
        self.assertIn("AI inference platform", items[0][1])

    def test_score_focuses_on_accel_guidance_tone(self):
        prev = {"tone": 4}
        # 새 동인·LLM '가속'만 많은 발표는 후보가 아니다 — 가속(기대 초과)·가이던스 상향·어조 상승 중 하나가 있어야 한다
        drivers_only = {"drivers": [{"status": "new"}] * 3 + [{"status": "accelerating", "magnitude": "up 40%"}] * 4,
                        "guidance": [{"direction": "initiated", "metric": "Q4 revenue"}], "tone": 4}
        self.assertEqual(cm.score(drivers_only, prev, []), (3.0, "none"))                  # 새 1 + 수치 가속 2
        raise_only = {"drivers": [], "guidance": [{"direction": "raised", "metric": "FY revenue"},
                                                  {"direction": "lowered", "metric": "tax rate"}], "tone": 4}
        self.assertEqual(cm.score(raise_only, prev, []), (3.0, "none"))                    # 상향 3, 세율 하향은 성장 지표 아님
        both = {**raise_only, "tone": 5}
        self.assertEqual(cm.score(both, prev, []), (5.0, "candidate"))                     # 상향 3 + 어조 2
        accel = {"on": True}
        self.assertEqual(cm.score({"drivers": [], "guidance": [], "tone": 5}, prev, [], accel), (5.0, "candidate"))  # 가속 3 + 어조 2
        cut = {**both, "guidance": both["guidance"] + [{"direction": "lowered", "metric": "FY revenue"}]}
        self.assertEqual(cm.score(cut, prev, [])[1], "none")                               # 성장 가이던스 하향이 있으면 아님
        self.assertEqual(cm.score(both, prev, [(5.0, "candidate")]), (5.0, "continuing"))  # 최근에도 모멘텀 → 이어지는 모멘텀
        self.assertEqual(cm.score(both, prev, [(5.0, "continuing")])[1], "continuing")
        self.assertEqual(cm.score(both, prev, [(5.0, "candidate"), (0.0, "none"), (0.0, "none")])[1], "candidate")
        self.assertEqual(cm.score(both, prev, [(2.0, "candidate")])[1], "candidate")         # 3점 이상 높으면 새 모멘텀
        self.assertEqual(cm.score(both, None, []), (0.0, "first"))

    def test_acceleration_numeric_needs_beat_or_raise(self):
        cur = {"guidance": [], "beyond_expectation": [{"basis": "guidance", "quote": "exceeded the high end"}]}
        num = {"quarter": "2026-09", "g_now": 61.2, "g_prev": 24.1, "gap": 37.1, "beat": None}
        self.assertFalse(cm.acceleration(cur, num)["on"])                              # 빨라졌지만 기대 비교 근거 없음
        self.assertTrue(cm.acceleration(cur, {**num, "beat": 2.5})["on"])              # 컨센서스 2.5% 상회
        self.assertFalse(cm.acceleration(cur, {**num, "beat": 0.4})["on"])             # 기대만큼 → 가속 아님
        raised = {**cur, "guidance": [{"direction": "raised", "metric": "FY revenue"}]}
        self.assertTrue(cm.acceleration(raised, num)["on"])                            # 가이던스 상향 = 회사 기대 초과
        self.assertFalse(cm.acceleration(raised, {**num, "gap": 1.0})["on"])           # 성장률이 거의 그대로면 아님
        q = cm.acceleration(cur, None)                                                 # 숫자 없으면 원문 근거
        self.assertEqual((q["on"], q["basis"]), (True, "quote"))
        self.assertEqual(cm.acceleration({"guidance": []}, None), {"on": False, "basis": "none"})

    def test_revenue_accel_from_quarters_and_consensus(self):
        c = db()
        c.executescript("""CREATE TABLE us_quarterly (ticker TEXT, q TEXT, metric TEXT, value REAL, tag TEXT, use_key TEXT, fetched_at TEXT,
                                                    UNIQUE(ticker, q, metric));
                           CREATE TABLE earnings_expectations (ticker TEXT, event_date TEXT, snapshot TEXT, quant_json TEXT);""")
        for q, v in [("2026-09", 4312.8), ("2026-06", 3274.3), ("2025-09", 2675.8), ("2025-06", 2638.1)]:
            c.execute("INSERT INTO us_quarterly (ticker, q, metric, value) VALUES ('VRT', ?, 'revenue', ?)", (q, v))
        c.execute("INSERT INTO earnings_expectations VALUES ('VRT','2026-10-28','d1', ?)", (json.dumps({"rev_est": 4100.0}),))
        r = cm.revenue_accel(c, "VRT", "2026-10-28")
        self.assertEqual((r["quarter"], r["g_now"], r["g_prev"], r["beat"]), ("2026-09", 61.2, 24.1, 5.2))
        self.assertIsNone(cm.revenue_accel(c, "VRT", "2027-06-01"))                    # 분기가 너무 오래됨 → 판정 불가
        self.assertIsNone(cm.revenue_accel(c, "ACME", "2026-10-28"))

    def test_beyond_expectation_quote_is_verified(self):
        p = cm.verify({"beyond_expectation": [{"basis": "guidance", "quote": "Revenue exceeded the high end of our guidance range"},
                                              {"basis": "consensus", "quote": "We crushed every estimate on the street"}]},
                      "Q3 recap: revenue exceeded the high end of our guidance range, driven by data center.")
        self.assertEqual([b["verified"] for b in p["beyond_expectation"]], [True, False])
        combined = cm._combine([{"source": "release", "payload": json.dumps(p)}])
        self.assertEqual(len(combined["beyond_expectation"]), 1)

    def test_new_driver_already_in_prior_text_is_not_new(self):
        d = cm.mentioned_before([{"name": "Greater China market", "status": "new"}, {"name": "Zoox robotaxi", "status": "new"}],
                                "Revenue in Greater China declined 3% while Americas grew.")
        self.assertEqual([x["status"] for x in d], ["accelerating", "new"])

    def test_renamed_driver_is_not_new(self):
        d = cm.downgrade_renamed([{"name": "app nights booked", "status": "new"}, {"name": "Delta partnership", "status": "new"}],
                                 ["Nights and experiences booked", "International expansion"])
        self.assertEqual([x["status"] for x in d], ["accelerating", "new"])

    def test_season_by_report_date(self):
        self.assertEqual(cm.season("2026-10-13")["key"], "2026Q3")
        self.assertEqual(cm.season("2026-08-26")["key"], "2026Q2")      # NVDA 8월 발표도 2분기 시즌
        self.assertEqual(cm.season("2026-02-10")["key"], "2025Q4")
        self.assertEqual(cm.season("2026-10-01")["start"], "2026-10-01")

    def test_by_season_moves_last_season_to_history(self):
        c = db()
        for t, d in [("ACME", "2026-08-26"), ("ACME", "2026-10-08")]:
            c.execute("INSERT INTO call_momentum (ticker, event_date, score, status, reasons) VALUES (?,?,8,'candidate',?)",
                      (t, d, json.dumps({"drivers": [], "guidance": [], "tone": None, "sources": [], "qa_focus": []})))
        from datetime import date
        r = cm.by_season(c, date(2026, 10, 13))
        self.assertEqual([x["event_date"] for x in r["candidates"]], ["2026-10-08"])
        self.assertEqual([(h["key"], len(h["candidates"])) for h in r["history"]], [("2026Q2", 1)])
        self.assertEqual(r["season"]["reported"], 1)
        c.execute("INSERT INTO call_momentum (ticker, event_date, score, status, reasons) VALUES ('ACME','2026-10-09',6,'continuing',?)",
                  (json.dumps({"drivers": [], "guidance": [], "tone": None, "sources": [], "qa_focus": []}),))
        r = cm.by_season(c, date(2026, 10, 13))
        self.assertEqual(([x["event_date"] for x in r["candidates"]], [x["event_date"] for x in r["continuing"]]),
                         (["2026-10-08"], ["2026-10-09"]))

    def test_failed_extraction_recorded_not_retried(self):
        c = db()
        add_release(c, 1, "2026-02-20", "text")
        self.assertEqual(cm.extract_pending(c, call=lambda p: "not json")["failed"], 1)
        self.assertEqual(cm.extract_pending(c, call=lambda p: "not json")["failed"], 0)

    def test_sec_requires_contact(self):
        import os
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            with self.assertRaises(sec.SecNotConfigured):
                sec._ua()
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_sec_to_text_keeps_paragraphs(self):
        t = sec.to_text("<p>Revenue &amp; growth</p><table><tr><td>Q1</td><td>$5</td></tr></table><script>x</script>")
        self.assertEqual(t, "Revenue & growth\nQ1 | $5")


if __name__ == "__main__":
    unittest.main()


class FiscalLabelTests(unittest.TestCase):
    def test_matches_alpha_vantage_labels(self):
        from pipeline.transcript import fiscal_label
        cases = [("2025-08-27", "0131", (2026, 2)), ("2026-05-20", "0131", (2027, 1)), ("2025-10-29", "0630", (2026, 1)),
                 ("2026-07-29", "0630", (2026, 4)), ("2026-01-29", "0926", (2026, 1)), ("2026-06-03", "1101", (2026, 2)),
                 ("2025-12-11", "0830", (2026, 1)), ("2026-05-28", "0830", (2026, 3)), ("2026-10-28", "1231", (2026, 3))]
        for d, fye, want in cases:
            self.assertEqual(fiscal_label(d, fye), want, (d, fye))


class ReconcileTests(unittest.TestCase):
    def test_future_or_far_dates_snap_to_sec(self):
        from pipeline.transcript import reconcile_call_dates
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
        c.executescript(sec.SCHEMA + """CREATE TABLE transcripts (id INTEGER PRIMARY KEY, raw_doc_id INT, ticker TEXT, fiscal_year INT, fiscal_period TEXT, call_date TEXT);
            CREATE TABLE transcript_follow (ticker TEXT, fiscal_year_end TEXT);
            CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, published_at TEXT);
            INSERT INTO raw_documents VALUES (11,'2026-10-13T04:29:33+00:00'),(12,'2026-05-09T00:00:00+00:00');
            INSERT INTO transcript_follow VALUES ('IREN','0630');
            INSERT INTO transcripts VALUES (1,11,'IREN',2026,'Q4','2026-12-01'),(2,12,'IREN',2026,'Q3','2026-05-08'),(3,NULL,'IREN',2026,'Q2',NULL);
            INSERT INTO earnings_releases (doc_id,ticker,accession,filing_date,exhibit_type) VALUES
              (1,'IREN','a','2026-08-27','EX-99.1'),(2,'IREN','b','2026-05-11','EX-99.1'),(3,'IREN','c','2026-02-12','EX-99.1'),
              (4,'IREN','d','2026-07-20','EX-99.1');""")   # 7/20 = 같은 분기 월간 업데이트(본 실적보다 먼저)
        r = reconcile_call_dates(c, today="2026-10-13")
        got = dict(c.execute("SELECT id, call_date FROM transcripts").fetchall())
        self.assertEqual(got, {1: "2026-08-27", 2: "2026-05-08", 3: "2026-02-12"})   # 미래·빈칸은 고치고 3일 차이는 둔다
        self.assertEqual(r["fixed"], 2)
        pub = dict(c.execute("SELECT id, published_at FROM raw_documents").fetchall())
        self.assertEqual(pub, {11: "2026-08-27", 12: "2026-05-09T00:00:00+00:00"})   # 수집 시각이 남은 게시일은 콜 날짜로, 하루 차이는 둔다
        self.assertEqual(r["published_synced"], 1)


class CanonicalEventTests(unittest.TestCase):
    def test_preliminary_filings_merge_into_last_of_quarter(self):
        c = db()
        c.execute("UPDATE transcript_follow SET fiscal_year_end='1231'")
        add_release(c, 1, "2026-07-02", "deliveries")      # TSLA식 인도량 8-K (2.02)
        add_release(c, 2, "2026-07-22", "earnings")
        add_release(c, 3, "2026-04-22", "earnings q1")
        self.assertEqual([(e["date"], sorted(d["doc_id"] for d in e["docs"])) for e in cm.events(c, "ACME")],
                         [("2026-04-22", [3]), ("2026-07-22", [1, 2])])


class CyLabelTests(unittest.TestCase):
    def test_calendar_quarter_by_middle_month(self):
        from pipeline.transcript import cy_label
        cases = [((2027, "Q2", "0131"), "CY2026 Q2"), ((2026, "Q1", "0630"), "CY2025 Q3"), ((2026, "Q4", "0630"), "CY2026 Q2"),
                 ((2026, "Q1", "0926"), "CY2025 Q4"), ((2026, "Q2", "1101"), "CY2026 Q1"), ((2026, "Q4", "0830"), "CY2026 Q3"),
                 ((2026, "Q3", "1231"), "CY2026 Q3"), ((2026, "Q2", None), None)]
        for (fy, p, fye), want in cases:
            self.assertEqual(cy_label(fy, p, fye), want, (fy, p, fye))

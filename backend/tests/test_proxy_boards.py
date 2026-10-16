"""프록시 보드 API (D-240) — CRUD · 항목 검증 422 · 상세는 LLM 0 · 제안은 유효/원천 없음 분리 · LLM 미가용 503."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from pipeline import enrich, proxy_adapters, proxy_boards as pb
from routers import proxy_boards

BASE = "/api/spine/proxy-boards"


def day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


class ProxyBoardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "t.sqlite"
        with patch.object(database, "DB_PATH", path):
            database.init_db()

        def connection():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        self.conn = connection
        c = connection()
        maturity = (date.today() + timedelta(days=365 * 5)).isoformat()
        c.execute("INSERT INTO credit_bonds (ticker, symbol, maturity) VALUES ('ORCL', 'X:ORCL', ?)", (maturity,))
        c.executemany("INSERT INTO treasury_curve (date, tenor, yield) VALUES (?,?,4.0)", [(day(n), t) for n in (45, 3) for t in (1, 10)])
        c.executemany("INSERT INTO credit_quotes (symbol, date, ytm) VALUES ('X:ORCL', ?, ?)", [(day(40), 6.0), (day(3), 7.0)])
        c.executemany("INSERT INTO market_indicators (snapshot_date, indicator, value) VALUES (?,?,?)",
                      [(day(35), "risk_hy", 3.5), (day(2), "risk_hy", 3.0)])
        c.execute("INSERT INTO proxy_registry (id, key, label, unit, modality) VALUES (50, 'capex', '하이퍼스케일러 CAPEX', '$B', 'numeric')")
        c.executemany("INSERT INTO proxy_observations (proxy_id, observed_at, value_num, source_type) VALUES (50, ?, ?, 'transcript')",
                      [("2026-07-01", 20.0), ("2026-09-10", 28.0)])
        c.commit()
        c.close()
        p = patch.object(proxy_boards, "get_connection", connection)
        p.start()
        self.addCleanup(p.stop)
        proxy_adapters._memo.clear()
        app = FastAPI()
        app.include_router(proxy_boards.router)
        self.client = TestClient(app)

    def create(self, name="AI 밸류체인 신용·수요", **kw):
        r = self.client.post(BASE, json={"name": name, **kw})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def add(self, board_id, **body):
        return self.client.post(f"{BASE}/{board_id}/items", json=body)

    def test_board_crud(self):
        bid = self.create(description="신용 긴장", question_id=7)
        self.assertEqual(self.client.post(BASE, json={"name": "AI 밸류체인 신용·수요"}).status_code, 409)
        boards = self.client.get(BASE).json()
        self.assertEqual([(b["name"], b["item_count"], b["question_id"]) for b in boards], [("AI 밸류체인 신용·수요", 0, 7)])
        r = self.client.patch(f"{BASE}/{bid}", json={"name": "AI 신용", "question_id": None})
        self.assertEqual((r.status_code, r.json()["name"], r.json()["question_id"], r.json()["description"]), (200, "AI 신용", None, "신용 긴장"))
        self.assertEqual(self.client.delete(f"{BASE}/{bid}").status_code, 204)
        self.assertEqual(self.client.get(f"{BASE}/{bid}").status_code, 404)
        self.assertEqual(self.client.get(BASE).json(), [])

    def test_items_add_validate_order_remove(self):
        bid = self.create()
        r = self.add(bid, label="오라클 스프레드", adapter="credit", adapter_ref="credit:ORCL", warn_direction="up", rationale="신용 긴장 선행")
        self.assertEqual(r.status_code, 201, r.text)
        orcl = r.json()["proxy_id"]
        self.assertEqual(self.add(bid, label="HY", adapter="indicator", adapter_ref="risk_hy", warn_direction="up").status_code, 201)
        self.assertEqual(self.add(bid, proxy_id=50).status_code, 201)
        self.assertEqual(self.add(bid, proxy_id=50).status_code, 409)
        wrap = self.add(bid, label="CAPEX(보드)", adapter="transcript", adapter_ref="transcript:50", warn_direction="down")
        self.assertEqual(wrap.status_code, 201, wrap.text)
        self.assertNotEqual(wrap.json()["proxy_id"], 50)             # 기존 질문 프록시를 덮어쓰지 않고 보드 소유 행을 만든다
        # 검증 실패는 422 — 모르는 어댑터·원천에 없는 ref·다른 어댑터의 ref·없는 프록시·필수값 누락·둘 다 보냄
        for bad in [dict(label="x", adapter="weather", adapter_ref="weather:seoul"),
                    dict(label="x", adapter="credit", adapter_ref="credit:NOPE"),
                    dict(label="x", adapter="credit", adapter_ref="indicator:risk_hy"),
                    dict(label="x", adapter="indicator", adapter_ref="indicator:made_up"),
                    dict(proxy_id=9999),
                    dict(adapter="credit", adapter_ref="credit:ORCL"),
                    dict(proxy_id=50, label="x", adapter="credit", adapter_ref="credit:ORCL"),
                    dict(label="x", adapter="credit", adapter_ref="credit:ORCL", warn_direction="sideways")]:
            with self.subTest(bad=bad):
                self.assertEqual(self.add(bid, **bad).status_code, 422)
        detail = self.client.get(f"{BASE}/{bid}").json()
        self.assertEqual([i["adapter_ref"] for i in detail["items"]], ["credit:ORCL", "indicator:risk_hy", "transcript:50", "transcript:50"])
        self.assertEqual([i["warn_direction"] for i in detail["items"][2:]], [None, "down"])
        self.assertEqual(detail["items"][3]["latest"]["value"], 28.0)
        ids = [i["proxy_id"] for i in detail["items"]]
        self.assertEqual(self.client.put(f"{BASE}/{bid}/items/order", json={"proxy_ids": ids[:2]}).status_code, 422)
        self.assertEqual(self.client.put(f"{BASE}/{bid}/items/order", json={"proxy_ids": list(reversed(ids))}).status_code, 204)
        self.assertEqual([i["proxy_id"] for i in self.client.get(f"{BASE}/{bid}").json()["items"]], list(reversed(ids)))
        self.assertEqual(self.client.delete(f"{BASE}/{bid}/items/{orcl}").status_code, 204)
        self.assertEqual(self.client.delete(f"{BASE}/{bid}/items/{orcl}").status_code, 404)
        c = self.conn()
        self.assertIsNone(c.execute("SELECT 1 FROM proxy_registry WHERE id=?", (orcl,)).fetchone())   # 보드가 만든 지표는 함께 정리
        self.assertIsNotNone(c.execute("SELECT 1 FROM proxy_registry WHERE id=50").fetchone())       # 기존 질문 프록시는 남긴다
        c.close()

    def test_detail_values_warn_and_no_llm(self):
        bid = self.create()
        self.add(bid, label="오라클 스프레드", adapter="credit", adapter_ref="credit:ORCL", warn_direction="up")
        self.add(bid, label="HY OAS", adapter="indicator", adapter_ref="indicator:risk_hy", warn_direction="up")
        with patch.object(enrich, "_call_claude_code", side_effect=AssertionError("GET에서 LLM 호출")):
            detail = self.client.get(f"{BASE}/{bid}")
            boards = self.client.get(BASE)
        self.assertEqual(detail.status_code, 200, detail.text)
        orcl, hy = detail.json()["items"]
        self.assertEqual((orcl["latest"]["value"], orcl["latest"]["as_of"], orcl["latest"]["change"], orcl["in_warn"]), (300.0, day(3), 100.0, True))
        self.assertEqual((hy["latest"]["value"], hy["latest"]["change"], hy["in_warn"]), (300.0, -50.0, False))
        self.assertEqual(hy["unit"], "bp")
        self.assertEqual([p["date"] for p in orcl["series"]], [day(40), day(3)])
        self.assertEqual(detail.json()["in_warn_count"], 1)
        self.assertEqual((boards.json()[0]["item_count"], boards.json()[0]["in_warn_count"]), (2, 1))

    def test_adapters_and_catalog(self):
        kinds = [a["kind"] for a in self.client.get(f"{BASE}/adapters").json()]
        self.assertEqual(kinds, ["credit", "trade", "call_momentum", "indicator", "retail", "sector", "price", "transcript", "corpus"])
        self.assertIn("credit:ORCL", [e["ref"] for e in self.client.get(f"{BASE}/adapters/credit/catalog?q=오라클").json()])
        self.assertEqual(self.client.get(f"{BASE}/adapters/weather/catalog").status_code, 404)

    def test_suggest_splits_valid_and_needs_source(self):
        reply = json.dumps([
            {"label": "오라클 회사채 스프레드", "adapter": "credit", "adapter_ref": "credit:ORCL", "unit": "%", "warn_direction": "up",
             "rationale": "AI 설비투자 차입 긴장", "lead_or_confirm": "lead"},
            {"label": "HY OAS", "adapter": "indicator", "adapter_ref": "indicator:risk_hy", "warn_direction": "up", "lead_or_confirm": "confirm"},
            {"label": "코어위브 스프레드", "adapter": "credit", "adapter_ref": "credit:CRWV", "warn_direction": "up", "rationale": "지어낸 원천"},
            {"label": "GPU 임대료", "adapter": None, "adapter_ref": None, "needed": "H100 시간당 임대 가격 시계열"},
        ], ensure_ascii=False)
        seen = []

        def fake_call(prompt, model="haiku", timeout=180, effort=None):
            seen.append((prompt, model))
            return "설명\n" + reply
        with patch.object(enrich, "llm_available", return_value=True), patch.object(enrich, "_call_claude_code", side_effect=fake_call):
            r = self.client.post(f"{BASE}/suggest", json={"topic": "AI 밸류체인 신용"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], "sonnet")
        self.assertIn("credit:ORCL", seen[0][0])                      # 프롬프트에 실제 카탈로그
        self.assertEqual([c["adapter_ref"] for c in body["candidates"]], ["credit:ORCL", "indicator:risk_hy"])
        self.assertEqual(body["candidates"][0]["unit"], "bp")          # 단위는 원천 기준
        self.assertEqual(body["candidates"][1]["lead_or_confirm"], "confirm")
        needs = {n["label"]: n for n in body["needs_source"]}
        self.assertEqual(set(needs), {"코어위브 스프레드", "GPU 임대료"})
        self.assertIn("credit:CRWV", needs["코어위브 스프레드"]["reason"])
        self.assertEqual(needs["GPU 임대료"]["reason"], "H100 시간당 임대 가격 시계열")

    def test_suggest_llm_unavailable_is_503(self):
        with patch.object(enrich, "llm_available", return_value=False), \
                patch.object(enrich, "_call_claude_code", side_effect=AssertionError("호출 금지")):
            r = self.client.post(f"{BASE}/suggest", json={"topic": "AI"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("LLM", r.json()["detail"])

    def test_suggest_unparseable_reply_is_502(self):
        with patch.object(enrich, "llm_available", return_value=True), patch.object(enrich, "_call_claude_code", return_value="죄송합니다"):
            self.assertEqual(self.client.post(f"{BASE}/suggest", json={"topic": "AI"}).status_code, 502)

    def test_keywords(self):
        self.assertEqual(pb.keywords("AI 밸류체인 신용·수요"), ["AI", "밸류체인", "신용", "수요"])


if __name__ == "__main__":
    unittest.main()

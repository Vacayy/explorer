"""업종 정정 표 (D-313 1~2).

- 원천 = companies.sector(현재 종목코드) → sector_map, 엔티티 MEMBER_OF는 companies에 없는 코드에만 보조.
- 정정(sector_overrides)이 원천을 이긴다. sector_map에 없는 대분류로의 정정은 버린다.
- 시드는 코드에서 심는다 — 다시 init해도 늘지 않고, 손으로 바꾼 행을 덮지 않는다. 시드가 넣은 행은 시드를 따라 고친다(D-315).
- D-315 밸류체인 기준: 장비·소재·기자재·방산·자동차 부품은 사업 업종, 단일 사업 중간지주는 사업 업종, 여러 사업 지주는 지주·기타.
- 대분류를 쓰는 모든 곳(산업 맵·Peer 비중·거래대금 상위·실적 시즌·산업 그룹 분포)이 같은 결과를 본다.
"""
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import database
from pipeline import kr_movers, kr_season, sector_overrides as so, sector_peers, sector_rs
from pipeline.sector_override_seed import SEED, SEED_D315, SEED_D317, SOURCE, SOURCE_D315, SOURCE_D317

BACKEND = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        self.conn = database.get_connection()
        self.addCleanup(self.conn.close)


class SeedTests(Base):
    def test_seed_rows_and_idempotent(self):
        n = self.conn.execute("SELECT count(*) FROM sector_overrides").fetchone()[0]
        self.assertEqual(n, len({code for code, *_ in SEED + SEED_D315 + SEED_D317}))
        self.assertEqual(so.seed(self.conn), 0)
        database.init_db()
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sector_overrides").fetchone()[0], n)

    def test_seed_keeps_manual_edit(self):
        self.conn.execute("UPDATE sector_overrides SET sector='금융', source='manual' WHERE stock_code='003550'")
        self.conn.commit()
        so.seed(self.conn)
        row = self.conn.execute("SELECT sector, source FROM sector_overrides WHERE stock_code='003550'").fetchone()
        self.assertEqual((row["sector"], row["source"]), ("금융", "manual"))

    def test_seed_updates_old_seed_rows_only(self):
        # 11-05 첫 시드가 넣은 '에코프로 → 지주·기타' 행은 D-315 값으로 고친다. 손으로 바꾼 행은 둔다.
        self.conn.execute("UPDATE sector_overrides SET sector='지주·기타', reason='old', source=? WHERE stock_code='086520'", (SOURCE,))
        self.conn.execute("UPDATE sector_overrides SET sector='지주·기타', source='manual' WHERE stock_code='008930'")
        self.conn.commit()
        self.assertEqual(so.seed(self.conn), 1)
        row = self.conn.execute("SELECT sector, source FROM sector_overrides WHERE stock_code='086520'").fetchone()
        self.assertEqual((row["sector"], row["source"]), ("2차전지·에너지소재", SOURCE_D315))
        row = self.conn.execute("SELECT sector, source FROM sector_overrides WHERE stock_code='008930'").fetchone()
        self.assertEqual((row["sector"], row["source"]), ("지주·기타", "manual"))
        self.assertEqual(so.seed(self.conn), 0)

    def test_seed_d315_value_chain(self):
        got = {c: s for c, _, s, _ in SEED + SEED_D315}
        self.assertEqual(got["009540"], "조선·해운·운송")       # HD한국조선해양 — 단일 사업 중간지주
        self.assertEqual(got["086520"], "2차전지·에너지소재")   # 에코프로
        self.assertEqual(got["008930"], "바이오·헬스케어")      # 한미사이언스
        self.assertEqual(got["0126Z0"], "바이오·헬스케어")      # 삼성에피스홀딩스
        self.assertEqual(got["006260"], "지주·기타")            # LS — 여러 사업 지주는 그대로
        self.assertEqual(got["042700"], "반도체·전자부품")      # 한미반도체 — 반도체 장비
        self.assertEqual(got["357780"], "반도체·전자부품")      # 솔브레인 — 반도체 소재
        self.assertEqual(got["082740"], "조선·해운·운송")       # 한화엔진 — 조선 기자재
        self.assertEqual(got["034020"], "전력·에너지")          # 두산에너빌리티 — 원전
        self.assertEqual(got["348370"], "2차전지·에너지소재")   # 엔켐 — 2차전지 소재
        for code in ("272210", "064350", "103140"):             # 한화시스템·현대로템·풍산 — 방산
            self.assertEqual(got[code], "항공·방산·우주")
        for code in ("161390", "018880"):                       # 한국타이어·한온시스템
            self.assertEqual(got[code], "자동차·모빌리티")
        for code in ("140410", "095700"):                       # 메지온·제넥신 — 연구개발 바이오
            self.assertEqual(got[code], "바이오·헬스케어")
        for code in ("092190", "329180", "042660", "047040"):   # 서울바이오시스·조선소·종합 건설은 현행
            self.assertNotIn(code, got)
        self.assertEqual(got["000720"], "건설·부동산")          # 현대건설 — 원전 EPC가 일부인 종합 건설

    def test_seed_known_cases(self):
        got = {c: s for c, _, s, _ in SEED + SEED_D315 + SEED_D317}
        self.assertEqual(got["003550"], "지주·기타")        # LG
        self.assertEqual(got["006260"], "지주·기타")        # LS
        self.assertEqual(got["229640"], "전력·에너지")      # LS에코에너지
        self.assertEqual(got["000720"], "건설·부동산")      # 현대건설
        self.assertEqual(got["375500"], "건설·부동산")      # DL이앤씨
        for code in ("090430", "051900", "192820", "161890", "278470"):   # 화장품 제조사
            self.assertEqual(got[code], "유통·소비재")
        self.assertNotIn("055550", got)   # 신한지주는 금융 그대로
        allowed = {"2차전지·에너지소재", "IT서비스·SW", "건설·부동산", "금융", "기계·장비", "미디어·엔터·게임", "바이오·헬스케어",
                   "반도체·전자부품", "유통·소비재", "음식료·농수산", "자동차·모빌리티", "전력·에너지", "조선·해운·운송",
                   "지주·기타", "철강·금속", "통신", "항공·방산·우주", "화학·소재"}
        self.assertTrue({s for _, _, s, _ in SEED + SEED_D315 + SEED_D317} <= allowed)
        self.assertEqual(len(got), len(SEED) + len(SEED_D315) + len(SEED_D317))   # 종목 중복 없음

    def test_seed_d317_robotics_to_machinery(self):
        # 로봇·자동화 관심 산업 그룹의 원천 '전동기…' 업종 두 종목을 기계·장비로(D-317). 기존 DB에도 다음 init에 들어간다
        self.assertEqual({c: s for c, _, s, _ in SEED_D317}, {"058610": "기계·장비", "160190": "기계·장비"})
        self.conn.execute("DELETE FROM sector_overrides WHERE source=?", (SOURCE_D317,))
        self.conn.commit()
        self.assertEqual(so.seed(self.conn), 2)
        rows = self.conn.execute("SELECT stock_code, sector, source FROM sector_overrides WHERE stock_code IN ('058610','160190')").fetchall()
        self.assertEqual(sorted(tuple(r) for r in rows), [("058610", "기계·장비", SOURCE_D317), ("160190", "기계·장비", SOURCE_D317)])


class EffectiveTests(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        c.execute("DELETE FROM sector_overrides")
        c.executemany("INSERT INTO sector_map (sector_name, group_name) VALUES (?, ?)",
                      [("기타 금융업", "금융"), ("반도체 제조업", "반도체·전자부품"), ("기타 화학제품 제조업", "화학·소재"),
                       ("일차전지 및 이차전지 제조업", "2차전지·에너지소재"), ("전력", "전력·에너지"), ("지주", "지주·기타")])
        c.executemany("INSERT INTO companies (corp_code, corp_name, stock_code, sector) VALUES (?, ?, ?, ?)",
                      [("C1", "LG", "003550", "기타 금융업"), ("C2", "SK하이닉스", "000660", "반도체 제조업"),
                       ("C3", "아모레퍼시픽", "090430", "기타 화학제품 제조업"), ("C4", "우리금융지주", "316140", "기타 금융업"),
                       ("C5", "LS에코에너지", "229640", "기타 금융업")])
        # 엔티티 그래프: 우리금융지주는 옛 코드(053000), 옛 코드만 있는 회사(999990)는 보조로 쓴다
        c.execute("INSERT INTO entities (id, type, name, status) VALUES (1, 'sector', '기타 금융업', 'active')")
        c.execute("INSERT INTO entities (id, type, name, status) VALUES (2, 'sector', '반도체 제조업', 'active')")
        c.execute("INSERT INTO entities (id, type, name, aliases, status) VALUES (10, 'company', '우리금융지주', '053000', 'active')")
        c.execute("INSERT INTO entities (id, type, name, aliases, status) VALUES (11, 'company', '옛회사', '999990', 'active')")
        c.executemany("INSERT INTO entity_relations (src_id, dst_id, rel_type) VALUES (?, ?, 'MEMBER_OF')", [(10, 1), (11, 2)])
        c.executemany("INSERT INTO sector_overrides (stock_code, sector, reason, source) VALUES (?, ?, 'r', 'test')",
                      [("003550", "지주·기타"), ("090430", "유통·소비재"), ("229640", "전력·에너지"), ("000660", "없는섹터")])
        c.commit()

    def test_base_and_override(self):
        base = so.base_sectors(self.conn)
        self.assertEqual(base["316140"], "금융")         # 현재 코드는 companies에서
        self.assertEqual(base["999990"], "반도체·전자부품")  # companies에 없는 코드는 엔티티로
        eff = so.effective_sectors(self.conn)
        self.assertEqual(eff["003550"], "지주·기타")
        self.assertEqual(eff["229640"], "전력·에너지")
        self.assertEqual(eff["000660"], "반도체·전자부품")  # sector_map에 없는 정정은 버림
        self.assertNotIn("090430", so.overrides(self.conn))  # '유통·소비재'는 이 테스트의 sector_map에 없다
        self.assertEqual(eff["090430"], "화학·소재")
        # 원천은 그대로
        self.assertEqual(self.conn.execute("SELECT sector FROM companies WHERE stock_code='003550'").fetchone()[0], "기타 금융업")

    def test_readers_see_overrides(self):
        # 산업 맵·드릴다운·산업 그룹 분포·Peer 비중이 쓰는 _members
        self.assertEqual(sector_rs._members(self.conn)["003550"], "지주·기타")
        # 거래대금 상위 — 우선주는 본주 섹터
        rows = [{"stock_code": "003550"}, {"stock_code": "003555"}, {"stock_code": "229640"}]
        kr_movers._attach_sector(self.conn, rows)
        self.assertEqual([r["sector"] for r in rows], ["지주·기타", "지주·기타", "전력·에너지"])
        # 실적 시즌 업종 대비
        comp, members = kr_season._company_map(self.conn)
        self.assertEqual(comp["C1"]["group"], "지주·기타")
        self.assertIn("003550", members["지주·기타"])
        self.assertNotIn("003550", members.get("금융", []))
        # 섹터 → Peer 비중
        runtime = SimpleNamespace(catalog=SimpleNamespace(
            asOf="2026-11-02", groups=[SimpleNamespace(id="power", name="전력", scope="value_chain")],
            companies=[SimpleNamespace(code="229640", groupIds=["power"])]))
        self.conn.execute("DELETE FROM sector_peer_map")
        self.conn.execute("INSERT INTO sector_peer_map (sector, peer_group_id) VALUES ('전력·에너지', 'power')")
        out = sector_peers.sector_peers(self.conn, runtime)
        power = next(s for s in out["sectors"] if s["sector"] == "전력·에너지")["links"][0]
        self.assertEqual((power["in_sector"], power["classified"], power["share"]), (1, 1, 1.0))

    def test_sector_map_rs_groups_follow_override(self):
        c = self.conn
        for code in ("003550", "000660", "316140"):
            for d, px in (("2025-11-01", 100), ("2026-10-01", 100), ("2026-10-25", 100), ("2026-11-03", 110)):
                c.execute("INSERT INTO stock_prices (stock_code, trade_date, close, market_cap) VALUES (?, ?, ?, ?)",
                          (code, d, px, 1e12))
        c.commit()
        sector_rs._cache.clear()
        self.addCleanup(sector_rs._cache.clear)
        groups = {g["name"]: g["stocks"] for g in sector_rs.compute_sector_map()["groups"]}
        self.assertEqual(groups, {"지주·기타": 1, "반도체·전자부품": 1, "금융": 1})


class NoBypassTests(unittest.TestCase):
    def test_no_reader_joins_sector_map_directly(self):
        """회사 → 대분류를 sector_map에서 직접 읽는 곳이 새로 생기면 정정이 빠진다 — 단일 원천만 허용."""
        hits = []
        for p in (BACKEND / "pipeline").rglob("*.py"):
            if p.name == "sector_overrides.py":
                continue
            if re.search(r"JOIN\s+sector_map", p.read_text()):
                hits.append(p.name)
        for p in (BACKEND / "routers").rglob("*.py"):
            if re.search(r"JOIN\s+sector_map", p.read_text()):
                hits.append(p.name)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

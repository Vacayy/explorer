"""유니버스(담당 섹터 커버리지) 시드 — industry_groups / industry_members.

유니버스는 원래 API/프론트로만 큐레이션돼 DB에만 존재했다(재현 불가). 이 파일이 그 상태를
코드로 고정한다 (D-075).

**개인 커버리지는 저장소에 넣지 않는다.** 아래 `EXAMPLE_UNIVERSE`는 구조를 보여주는 예시일
뿐이고, 실제로 추적하는 유니버스는 `scripts/universe.local.json`(gitignore)에 둔다. 그 파일이
있으면 그것을 쓰고, 없으면 예시로 시드한다 — 공개 저장소에 커버리지를 노출하지 않으면서
개인 환경의 재현 가능성은 유지하기 위한 분리다.

로컬 파일 형식:
  [{"name": "반도체", "description": "...",
    "members": [{"code": "005930", "category": "제조·종합", "sort_order": 10}, ...]}, ...]

규율:
- 멱등: 반복 실행해도 결과 동일. 그룹은 이름(UNIQUE)으로 INSERT OR IGNORE, 멤버는
  (group_id, stock_code) UNIQUE로 INSERT OR REPLACE(category·sort_order 갱신).
- 비파괴: 여기 안 적힌 멤버(사용자가 UI로 추가한 것)는 삭제하지 않는다 — 추가·갱신만.
- stock_code는 companies 테이블에 실재하는 코드만(이름·주가 resolve 위해).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db

LOCAL = pathlib.Path(__file__).resolve().parent / "universe.local.json"

# 구조 예시 — 대표 대형주 소수만. 실제 커버리지는 universe.local.json (gitignore).
EXAMPLE_UNIVERSE = [
    ("반도체", "메모리·HBM·후공정 밸류체인", [
        ("005930", "제조·종합", 10), ("000660", "제조·종합", 20),
    ]),
    ("2차전지", "셀·소재 밸류체인", [
        ("373220", "셀", 10), ("006400", "셀", 20),
    ]),
    ("자동차·전장", "완성차·부품·전장 밸류체인", [
        ("005380", "완성차", 10), ("000270", "완성차", 20),
    ]),
]


def load_universe() -> list:
    """로컬 정본이 있으면 그것을, 없으면 예시를 반환."""
    if LOCAL.exists():
        data = json.loads(LOCAL.read_text())
        return [(g["name"], g.get("description", ""),
                 [(m["code"], m.get("category", ""), m.get("sort_order", 0)) for m in g["members"]])
                for g in data]
    return EXAMPLE_UNIVERSE


def seed() -> dict:
    init_db()
    conn = get_connection()
    groups_added = 0
    members_upserted = 0
    for name, desc, members in load_universe():
        conn.execute(
            "INSERT OR IGNORE INTO industry_groups (name, description) VALUES (?, ?)", (name, desc))
        conn.execute("UPDATE industry_groups SET description=? WHERE name=?", (desc, name))
        row = conn.execute("SELECT id FROM industry_groups WHERE name=?", (name,)).fetchone()
        gid = row[0]
        for code, category, order in members:
            cur = conn.execute(
                "INSERT OR REPLACE INTO industry_members (group_id, stock_code, category, sort_order) "
                "VALUES (?, ?, ?, ?)", (gid, code, category, order))
            members_upserted += cur.rowcount
    conn.commit()
    groups_added = conn.execute("SELECT COUNT(*) FROM industry_groups").fetchone()[0]
    conn.close()
    return {"groups_total": groups_added, "members_upserted": members_upserted}


if __name__ == "__main__":
    print(seed())

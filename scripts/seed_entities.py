"""companies 테이블을 그래프 entities로 시딩한다.

- company 노드: 각 상장사 (aliases=stock_code, meta=corp_code/market/sector)
- sector 노드: distinct sector
- MEMBER_OF 엣지: company -> sector (epistemic_type='fact')

멱등: 재실행해도 중복 생성하지 않는다.
(entity_relations UNIQUE는 valid_from NULL을 서로 다르게 보므로,
 INSERT OR IGNORE 대신 명시적 존재 체크로 dedupe 한다.)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection, init_db


def _get_or_create_entity(conn, type_, name, aliases=None, meta=None):
    row = conn.execute(
        "SELECT id FROM entities WHERE type=? AND name=?", (type_, name)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO entities (type, name, aliases, meta_json) VALUES (?,?,?,?)",
        (type_, name, aliases, json.dumps(meta, ensure_ascii=False) if meta else None),
    )
    return cur.lastrowid


def _ensure_relation(conn, src_id, dst_id, rel_type):
    exists = conn.execute(
        "SELECT 1 FROM entity_relations WHERE src_id=? AND dst_id=? AND rel_type=?",
        (src_id, dst_id, rel_type),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO entity_relations (src_id, dst_id, rel_type, epistemic_type, confidence) "
        "VALUES (?,?,?, 'fact', 1.0)",
        (src_id, dst_id, rel_type),
    )
    return True


def seed_entities():
    init_db()
    conn = get_connection()
    companies = conn.execute(
        "SELECT corp_code, corp_name, stock_code, market, sector FROM companies"
    ).fetchall()

    n_company = 0
    new_members = 0
    sector_ids = {}

    for co in companies:
        meta = {"corp_code": co["corp_code"], "market": co["market"], "sector": co["sector"]}
        cid = _get_or_create_entity(conn, "company", co["corp_name"], co["stock_code"], meta)
        n_company += 1

        sector = (co["sector"] or "").strip()
        if sector:
            if sector not in sector_ids:
                sector_ids[sector] = _get_or_create_entity(conn, "sector", sector)
            if _ensure_relation(conn, cid, sector_ids[sector], "MEMBER_OF"):
                new_members += 1

    conn.commit()
    n_ent_company = conn.execute("SELECT count(*) FROM entities WHERE type='company'").fetchone()[0]
    n_ent_sector = conn.execute("SELECT count(*) FROM entities WHERE type='sector'").fetchone()[0]
    conn.close()

    print(f"companies processed: {n_company}")
    print(f"entities: company={n_ent_company}, sector={n_ent_sector}")
    print(f"MEMBER_OF edges newly created this run: {new_members}")


if __name__ == "__main__":
    seed_entities()

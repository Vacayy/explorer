"""회사 → 산업 맵 대분류 (D-313 1~2) — 원천 분류 + 정정 표. 모델 호출 없음.

원천: `companies.sector`(DART KSIC 업종, 현재 종목코드) → `sector_map.group_name`. 엔티티 그래프의
MEMBER_OF(회사 → KSIC 업종)는 종목코드가 바뀐 회사(우리금융지주·미래에셋증권·SK 등 25곳)를 옛 코드로 들고 있어,
`companies`에 없는 코드에만 보조로 쓴다(두 경로의 KSIC는 겹치는 코드에서 모두 같다, 11-05 실측).
정정: `sector_overrides`(추가형). 원천 데이터는 덮어쓰지 않는다. 초안은 `sector_override_seed.SEED`를
코드에서 심는다(`seed`, INSERT OR IGNORE — 이미 있는 행은 건드리지 않는다).

대분류를 쓰는 곳은 모두 `effective_sectors`를 읽는다: 산업 맵 RS(sector_rs), 섹터 → Peer 비중(sector_peers),
국장 거래대금 상위(kr_movers), 국내 실적 시즌 업종 대비(kr_season), 산업 그룹의 맵 분포(industries).
"""
from pipeline.sector_override_seed import SEED, SOURCE


def seed(conn) -> int:
    """코드의 정정 초안을 심는다 → 새로 들어간 행 수. 같은 종목 행이 이미 있으면 그대로 둔다(멱등)."""
    before = conn.total_changes
    conn.executemany("""INSERT OR IGNORE INTO sector_overrides (stock_code, sector, reason, source)
                        VALUES (?, ?, ?, ?)""", [(code, sector, reason, SOURCE) for code, _, sector, reason in SEED])
    conn.commit()
    return conn.total_changes - before


def overrides(conn) -> dict[str, str]:
    """종목코드 → 정정 대분류. sector_map에 없는 대분류는 버린다(맵에 새 섹터가 생기지 않게)."""
    return {r[0]: r[1] for r in conn.execute("""SELECT o.stock_code, o.sector FROM sector_overrides o
        WHERE o.sector IN (SELECT DISTINCT group_name FROM sector_map)""")}


def base_sectors(conn) -> dict[str, str]:
    """종목코드 → 원천 대분류(정정 전)."""
    out = {r[0]: r[1] for r in conn.execute("""
        SELECT c.aliases, sm.group_name
        FROM entity_relations er
        JOIN entities c ON c.id = er.src_id AND c.type='company' AND c.aliases IS NOT NULL
        JOIN entities s ON s.id = er.dst_id AND s.type='sector'
        JOIN sector_map sm ON sm.sector_name = s.name
        WHERE er.rel_type='MEMBER_OF'""")}
    out.update({r[0]: r[1] for r in conn.execute("""
        SELECT c.stock_code, sm.group_name FROM companies c JOIN sector_map sm ON sm.sector_name = c.sector
        WHERE c.stock_code IS NOT NULL AND c.stock_code != ''""")})
    return out


def effective_sectors(conn) -> dict[str, str]:
    """종목코드 → 대분류(원천 + 정정). 대분류를 쓰는 모든 곳의 단일 원천."""
    out = base_sectors(conn)
    out.update(overrides(conn))
    return out

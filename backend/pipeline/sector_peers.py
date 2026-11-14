"""산업·섹터 → Peer 그룹 대응표 (ia-redesign §4.12, D-301 6) — 모델 호출 없음.

- 사람이 정한 대응은 `sector_peer_map`(source='seed')에 둔다. 코드의 `SEED`가 source='seed' 행의 원본이다 —
  `seed`가 init마다 맞춘다(없는 연결은 넣고, SEED에서 뺀 연결은 지우고, 순서·부분·범위는 고친다). 연결을 빼려면 SEED에서 지운다.
  source가 'seed'가 아닌 행(손으로 넣은 연결)은 건드리지 않는다.
- 검증: 연결된 그룹마다 구성 종목이 그 섹터에 몇 %인지(`share`) 센다. 섹터는 산업 맵(/map)과 같은
  `sector_rs._members`(회사 → MEMBER_OF → KSIC 업종 → sector_map 대분류)로 본다. 섹터를 모르는 종목은 분모에서 뺀다.
- 자동 제안: 연결이 하나도 없는 섹터에, 구성 종목의 AUTO_SHARE 이상이 그 섹터이고(그 섹터 종목 AUTO_MIN_MEMBERS 이상)
  아직 어느 섹터에도 걸리지 않은 그룹을 source='auto'로 붙여 보여 준다. 읽을 때 계산하고 저장하지 않는다.
"""
from collections import Counter

AUTO_SHARE = 0.6
AUTO_MIN_MEMBERS = 2

# 대응표 (§4.12 표 11-04 초안 → D-316·D-318 11-05). partial = 섹터의 일부 업종만 덮는 연결(사람 판단), note = 그 범위
# D-316: 업종 정정으로 비중 0%가 된 기계·장비 → 원전 기자재·피팅 3개, 화학·소재 → 반도체 화학 소재를 뺐다.
# D-318: 기계·장비 → 로봇·자동화.
SEED: list[dict] = [
    {"sector": "반도체·전자부품", "groups": ["semiconductor_value_chain"]},
    {"sector": "금융", "groups": ["bank_financial_holding", "securities_brokerage"]},
    {"sector": "2차전지·에너지소재", "groups": ["battery_value_chain"]},
    {"sector": "전력·에너지", "groups": ["power_infrastructure", "nuclear_value_chain"]},
    {"sector": "조선·해운·운송", "groups": ["shipbuilding"]},
    {"sector": "항공·방산·우주", "groups": ["defense_value_chain"]},
    {"sector": "유통·소비재", "groups": ["beauty_value_chain"], "partial": True, "note": "화장품만"},
    {"sector": "건설·부동산", "groups": ["plant_epc", "nuclear_epc"], "partial": True, "note": "플랜트·원전 건설만"},
    {"sector": "기계·장비", "groups": ["robotics_automation"], "partial": True, "note": "로봇·자동화만"},
    {"sector": "화학·소재", "groups": ["diversified_materials"], "partial": True, "note": "반도체 소재 중심"},
]


def seed_rows() -> list[tuple]:
    """(sector, peer_group_id, sort, partial, note) — SEED 전체."""
    return [(e["sector"], gid, i, int(e.get("partial", False)), e.get("note"))
            for e in SEED for i, gid in enumerate(e["groups"])]


def seed(conn) -> int:
    """source='seed' 행을 SEED에 맞춘다 → 넣고·고치고·지운 행 수(멱등: 다시 부르면 0). 다른 source 행은 두고,
    같은 (섹터, 그룹)에 손으로 넣은 행이 있으면 그 행을 그대로 둔다."""
    rows = seed_rows()
    before = conn.total_changes
    conn.executemany("""INSERT INTO sector_peer_map (sector, peer_group_id, sort, partial, note, source)
        VALUES (?, ?, ?, ?, ?, 'seed')
        ON CONFLICT(sector, peer_group_id) DO UPDATE SET sort=excluded.sort, partial=excluded.partial, note=excluded.note,
            updated_at=datetime('now')
        WHERE sector_peer_map.source = 'seed'
          AND (sector_peer_map.sort, sector_peer_map.partial, sector_peer_map.note)
              IS NOT (excluded.sort, excluded.partial, excluded.note)""", rows)
    keep = {(r[0], r[1]) for r in rows}
    gone = [(r[0], r[1]) for r in conn.execute("SELECT sector, peer_group_id FROM sector_peer_map WHERE source = 'seed'")
            if (r[0], r[1]) not in keep]
    conn.executemany("DELETE FROM sector_peer_map WHERE sector = ? AND peer_group_id = ? AND source = 'seed'", gone)
    conn.commit()
    return conn.total_changes - before


def group_shares(members: dict[str, list[str]], sector_of: dict[str, str]) -> dict[str, dict]:
    """그룹 id → {members, classified, by_sector: Counter}. members = 그룹 → 종목코드 목록."""
    out = {}
    for gid, codes in members.items():
        known = [sector_of[c] for c in codes if c in sector_of]
        out[gid] = {"members": len(codes), "classified": len(known), "by_sector": Counter(known)}
    return out


def _link(gid: str, name: str, scope: str, stat: dict | None, sector: str, *, source: str, partial: bool) -> dict:
    stat = stat or {"members": 0, "classified": 0, "by_sector": Counter()}
    n = stat["by_sector"].get(sector, 0)
    return {"group_id": gid, "group_name": name, "scope": scope, "source": source, "partial": partial,
            "members": stat["members"], "classified": stat["classified"], "in_sector": n,
            "share": round(n / stat["classified"], 3) if stat["classified"] else None}


def _covered(gid: str, linked: set[str], members: dict[str, list[str]]) -> bool:
    """이미 어느 섹터에 걸린 그룹인가 — 직접 걸렸거나, 구성 종목 전부가 걸린 그룹 하나에 들어 있다(그 아래 사업군)."""
    if gid in linked:
        return True
    codes = set(members.get(gid) or [])
    return bool(codes) and any(codes <= set(members.get(p) or []) for p in linked if p != gid)


def build(sectors: list[str], rows: list[dict], groups: list[dict], members: dict[str, list[str]],
          sector_of: dict[str, str]) -> list[dict]:
    """섹터마다 {sector, partial, note, links[]} — 순수 계산(테스트 대상).

    rows = sector_peer_map 행, groups = [{id, name, scope}] (Peer 카탈로그), members = 그룹 → 종목코드.
    카탈로그에 없는 그룹 id는 버린다."""
    info = {g["id"]: g for g in groups}
    stats = group_shares(members, sector_of)
    by_sector: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: (r["sector"], r["sort"], r["peer_group_id"])):
        g = info.get(r["peer_group_id"])
        if g:
            by_sector.setdefault(r["sector"], []).append(r)
    linked = {r["peer_group_id"] for rs in by_sector.values() for r in rs}
    out = []
    for sector in sectors:
        seeded = by_sector.get(sector, [])
        links = [_link(r["peer_group_id"], info[r["peer_group_id"]]["name"], info[r["peer_group_id"]]["scope"],
                       stats.get(r["peer_group_id"]), sector, source=r["source"], partial=bool(r["partial"])) for r in seeded]
        if not links:
            cands = [_link(g["id"], g["name"], g["scope"], stats.get(g["id"]), sector, source="auto", partial=False) for g in groups
                     if not _covered(g["id"], linked, members)]
            links = sorted([c for c in cands if c["share"] is not None and c["share"] >= AUTO_SHARE and c["in_sector"] >= AUTO_MIN_MEMBERS],
                           key=lambda c: (-c["share"], -c["in_sector"], c["group_name"]))
        note = next((r["note"] for r in seeded if r["note"]), None)
        out.append({"sector": sector, "partial": any(l["partial"] for l in links), "note": note, "links": links})
    return out


def sector_peers(conn, runtime) -> dict:
    """GET /api/spine/sector-map/peers 본문. runtime = routers.peers.read_runtime() 결과."""
    from pipeline.sector_rs import _members
    sectors = [r[0] for r in conn.execute("SELECT DISTINCT group_name FROM sector_map ORDER BY group_name")]
    rows = [dict(r) for r in conn.execute("SELECT sector, peer_group_id, sort, partial, note, source FROM sector_peer_map")]
    groups = [{"id": g.id, "name": g.name, "scope": g.scope} for g in runtime.catalog.groups]
    members: dict[str, list[str]] = {}
    for c in runtime.catalog.companies:
        for gid in c.groupIds:
            members.setdefault(gid, []).append(c.code)
    return {"catalog_as_of": str(runtime.catalog.asOf), "auto_share": AUTO_SHARE,
            "sectors": build(sectors, rows, groups, members, _members(conn))}

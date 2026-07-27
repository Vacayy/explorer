"""섹터 집약 (D-074, docs/specs/sector-aggregation.md) — 유니버스 그룹을 커버리지 단위로.

섹터는 소유가 아니라 **집약 뷰(N:M)**: 한 내러티브가 여러 섹터 뷰에 등장. 매핑은 결정적(LLM 0) —
내러티브 topic 엔티티가 그룹 멤버 종목과 **문서 공동언급**되는가. 스필오버 배제 2필터(D-074 튜닝):
- **카테고리**: 섹터 뷰는 산업/기술 렌즈만 — 매크로·지정학·수급(flow)만인 내러티브는 세계관 축으로.
- **지배 섹터**: 그 내러티브가 가장 많이 다루는 섹터의 뷰에만(멤버 겹침 기반, 이름 매칭 아님) — 타 섹터를
  비교로 언급한 스필오버(바이오·2차전지 "반도체 다음 순환매") 배제. dominance 비율로 진짜 N:M은 보존.
"""
from database import get_connection
from pipeline.signals import THEME_STOPWORDS

# 섹터 뷰에 넣을 도메인 렌즈 (내러티브 category CSV에 하나라도 포함되면 산업성 내러티브로 간주)
_SECTOR_LENSES = ("industry", "tech")


def sector_narratives(group_id: int, min_co: int = 3, min_relevance: float = 0.3,
                      limit: int = 15) -> list[dict]:
    """유니버스 그룹 G를 '건드리는' 내러티브 집약 (Phase 1 + 스필오버 배제 튜닝). LLM 0.

    포함 조건: co_docs≥min_co · relevance(co/topic전체)≥min_relevance · category에 산업/기술 렌즈(매크로·
    지정학·수급 전용 배제) · topic이 **다른 유니버스 그룹의 홈이 아님**(바이오·2차전지는 자기 섹터 뷰로).
    임계는 0.3 유지(0.35는 AI 0.33을 죽임 — relevance는 broad theme와 spillover를 못 가름, 실측).
    """
    conn = get_connection()
    target = {r["doc_id"] for r in conn.execute(
        "SELECT DISTINCT doc_id FROM entity_links WHERE entity_id IN ("
        "  SELECT id FROM entities WHERE type='company' AND aliases IN ("
        "    SELECT stock_code FROM industry_members WHERE group_id=?))", (group_id,)).fetchall()}
    if not target:
        conn.close()
        return []
    # 다른 유니버스 그룹 이름 (스필오버 배제 — 그 섹터 narrative는 자기 홈 뷰로. 그룹 6개라 이름 매칭 견고)
    others = [r["name"] for r in conn.execute(
        "SELECT name FROM industry_groups WHERE id != ?", (group_id,)).fetchall()]

    def is_other_home(topic: str) -> bool:
        return any(topic == o or topic in o or o in topic for o in others)

    narrs = conn.execute(
        "SELECT id, topic, title, category, created_at FROM narratives "
        "WHERE superseded_at IS NULL AND kind='topic'").fetchall()
    best: dict[int, dict] = {}
    for n in narrs:
        topic, cat = n["topic"], (n["category"] or "")
        if topic in THEME_STOPWORDS or is_other_home(topic):
            continue
        if not any(lens in cat for lens in _SECTOR_LENSES):   # 매크로·지정학·수급 전용 → 세계관 축
            continue
        tent = conn.execute(
            "SELECT id FROM entities WHERE name=? AND type IN ('theme','sector','industry')", (topic,)).fetchall()
        if not tent:
            continue
        tdocs: set = set()
        for e in tent:
            tdocs |= {r["doc_id"] for r in conn.execute(
                "SELECT doc_id FROM entity_links WHERE entity_id=?", (e["id"],)).fetchall()}
        co_g = len(tdocs & target)
        if not tdocs or co_g < min_co or (co_g / len(tdocs)) < min_relevance:
            continue
        if n["id"] in best and best[n["id"]]["co_docs"] >= co_g:
            continue
        best[n["id"]] = {"id": n["id"], "topic": topic, "title": n["title"], "category": n["category"],
                         "co_docs": co_g, "relevance": round(co_g / len(tdocs), 2), "created_at": n["created_at"]}
    conn.close()
    return sorted(best.values(), key=lambda x: -x["co_docs"])[:limit]

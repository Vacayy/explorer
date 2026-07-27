"""섹터 집약 (D-074, docs/specs/sector-aggregation.md) — 유니버스 그룹을 커버리지 단위로.

섹터는 소유가 아니라 **집약 뷰(N:M)**: 한 내러티브가 여러 섹터 뷰에 등장. 매핑은 결정적(LLM 0) —
내러티브의 topic 엔티티가 그룹의 멤버 종목과 **문서 공동언급**되는가(관련도 필터로 편재 라벨 배제).
"""
from database import get_connection
from pipeline.signals import THEME_STOPWORDS


def sector_narratives(group_id: int, min_co: int = 3, min_relevance: float = 0.3,
                      limit: int = 15) -> list[dict]:
    """유니버스 그룹 G를 '건드리는' 내러티브 집약 (Phase 1). LLM 0.

    G의 멤버 종목이 언급된 문서와, 각 내러티브 topic 엔티티가 공동언급되는 정도로 매핑.
    - co_docs: 그 topic이 멤버 종목과 함께 언급된 문서 수 (min_co 이상)
    - relevance: co_docs / topic 전체 언급 문서 (min_relevance 이상 — 편재 라벨·범용 테마 배제, D-035)
    문서유형 라벨(THEME_STOPWORDS) 제외. co_docs 내림차순.
    """
    conn = get_connection()
    narrs = {n["topic"]: dict(n) for n in conn.execute(
        "SELECT id, topic, title, category, created_at FROM narratives "
        "WHERE superseded_at IS NULL AND kind='topic'").fetchall()}
    # 멤버 종목과 공동언급된 theme/sector/industry 엔티티 (CTE로 큰 IN 회피 — SQLite 변수 한도)
    co_rows = conn.execute(
        "WITH member_docs AS ("
        "  SELECT DISTINCT doc_id FROM entity_links WHERE entity_id IN ("
        "    SELECT id FROM entities WHERE type='company' AND aliases IN ("
        "      SELECT stock_code FROM industry_members WHERE group_id=?))) "
        "SELECT e.id AS eid, e.name AS name, COUNT(DISTINCT el.doc_id) AS co "
        "FROM entity_links el JOIN entities e ON e.id=el.entity_id "
        "WHERE el.doc_id IN (SELECT doc_id FROM member_docs) "
        "  AND e.type IN ('theme','sector','industry') "
        "GROUP BY e.id", (group_id,)).fetchall()
    # 내러티브 id로 중복 제거 (같은 topic이 파편화 엔티티 여러 개로 매칭될 수 있음 — 최대 co 유지)
    best: dict[int, dict] = {}
    for r in co_rows:
        name = r["name"]
        if name in THEME_STOPWORDS or name not in narrs or r["co"] < min_co:
            continue
        total = conn.execute(
            "SELECT COUNT(DISTINCT doc_id) FROM entity_links WHERE entity_id=?", (r["eid"],)).fetchone()[0]
        rel = (r["co"] / total) if total else 0.0
        if rel < min_relevance:
            continue
        n = narrs[name]
        nid = n["id"]
        if nid in best and best[nid]["co_docs"] >= r["co"]:
            continue
        best[nid] = {"id": nid, "topic": name, "title": n["title"], "category": n["category"],
                     "co_docs": r["co"], "relevance": round(rel, 2), "created_at": n["created_at"]}
    conn.close()
    out = sorted(best.values(), key=lambda x: -x["co_docs"])
    return out[:limit]

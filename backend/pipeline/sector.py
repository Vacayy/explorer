"""섹터 집약 (D-074·D-077, docs/specs/sector-aggregation.md) — 유니버스 그룹을 커버리지 단위로.

섹터는 소유가 아니라 **집약 뷰(N:M)**: 한 내러티브가 여러 섹터 뷰에 등장. 매핑은 결정적(LLM 0) —
내러티브 topic 엔티티가 그룹 멤버 종목과 **문서 공동언급**되는가.

**지배 섹터 랭크(D-077)** — 구 관련도 필터(co/topic전체 ≥0.3)가 광역 내러티브를 죽였다: AI는 분모(전체
문서)가 커 어느 섹터서도 0.3 미달 → 반도체 1곳만 생존(실측 인터넷 162건·자동차 122건인데도 배제).
광역일수록 1:N으로 눌리는 역설. 교체 = **공동언급 지배 랭크** + **섹터명 홈 필터** 2겹:
- **지배 랭크**: 내러티브별 그룹 co 랭킹에서 지배도(co_g/최대섹터 co)≥`min_dominance` & 상위 `top_k`섹터.
  → 크로스커팅 테마(AI→반도체·인터넷·자동차)는 진짜 N:M, 좁은 테마(HBM→반도체)는 좁게. co 절대값 랭크라
  '광역이라 분모가 큰' 페널티가 없다.
- **섹터명 홈 필터**(`is_other_home`): topic이 **다른 유니버스 그룹 이름**이면 그 그룹 홈 뷰로만(바이오·반도체·
  방산 내러티브가 편재 대형주 공동언급 때문에 남의 섹터 뷰에 오르던 상호오염 차단). 섹터명이 아닌 테마는 무영향.
카테고리 필터(산업/기술 렌즈만 — 매크로·지정학·수급 전용은 세계관 축)는 유지.
"""
from database import get_connection
from pipeline.signals import THEME_STOPWORDS

# 섹터 뷰에 넣을 도메인 렌즈 (내러티브 category CSV에 하나라도 포함되면 산업성 내러티브로 간주)
_SECTOR_LENSES = ("industry", "tech")


def _group_docs(conn, group_id: int) -> set:
    """그룹 멤버 종목이 언급된 문서 집합."""
    return {r["doc_id"] for r in conn.execute(
        "SELECT DISTINCT doc_id FROM entity_links WHERE entity_id IN ("
        "  SELECT id FROM entities WHERE type='company' AND aliases IN ("
        "    SELECT stock_code FROM industry_members WHERE group_id=?))", (group_id,)).fetchall()}


def sector_narratives(group_id: int, min_co: int = 3, min_dominance: float = 0.15,
                      top_k: int = 4, limit: int = 15) -> list[dict]:
    """유니버스 그룹 G를 '건드리는' 내러티브 집약 — 지배 섹터 랭크(D-077). LLM 0.

    포함: co_g≥min_co · 지배도(co_g/최대섹터 co)≥min_dominance · G가 상위 top_k 섹터 · topic이 다른
    유니버스 그룹 홈이 아님 · category 산업/기술 렌즈. 진짜 N:M(AI→반도체·인터넷·자동차) 복원.
    """
    conn = get_connection()
    grows = conn.execute("SELECT id, name FROM industry_groups").fetchall()
    gdocs = {r["id"]: _group_docs(conn, r["id"]) for r in grows}
    if not gdocs.get(group_id):
        conn.close()
        return []
    # 다른 유니버스 그룹 이름 (섹터명 내러티브는 자기 홈 뷰로 — 상호오염 차단, 그룹 ~11개라 이름 매칭 견고)
    others = [r["name"] for r in grows if r["id"] != group_id]

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
        if not tdocs:
            continue
        # 그룹별 공동언급 → 지배 섹터 랭크 (co 절대값 — 광역 페널티 없음)
        co_by_g = {gid: len(tdocs & docs) for gid, docs in gdocs.items()}
        co_g = co_by_g[group_id]
        top_co = max(co_by_g.values())
        if co_g < min_co or top_co == 0 or (co_g / top_co) < min_dominance:
            continue
        if sum(1 for v in co_by_g.values() if v > co_g) >= top_k:   # G가 상위 top_k 밖
            continue
        best[n["id"]] = {"id": n["id"], "topic": topic, "title": n["title"], "category": n["category"],
                         "co_docs": co_g, "relevance": round(co_g / top_co, 2),  # relevance = 지배도
                         "created_at": n["created_at"]}
    conn.close()
    return sorted(best.values(), key=lambda x: -x["co_docs"])[:limit]

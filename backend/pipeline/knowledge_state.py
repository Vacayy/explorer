"""지식의 salience × conviction 위치 (LLM 0) — 시장 주목 vs 진리근접도 분리.

"반복=지식"의 함정을 피하기 위해 두 축을 직교로 계량하고, 그 갭 자체를 신호로 삼는다
(설계 §G). conviction은 근거의 강도(독립 관측·다양성·느린 층·반박), salience는 지금
시장이 이 주제를 얼마나 회자하나(주체 엔티티 최근 언급량).

4상태(사용자 확정 라벨):
  주목↑확신↓ overhyped   확신 대비 과한 주목 (진자 경고)
  주목↑확신↑ priced_in   주목받는 확신     (선반영·엣지 소진)
  주목↓확신↑ hidden_edge 주목받지 않은 확신 (기회·소외)
  주목↓확신↓ noise       단순 노이즈       (무시)
"""

# pace 층이 느릴수록(구조적일수록) 같은 근거라도 진실 가중이 높다
_LAYER_W = {"event": 0.0, "flow": 0.1, "cycle": 0.3, "structure": 0.6, "regime": 0.7}

CONV_HIGH = 0.5      # conviction 高 임계
SAL_HIGH = 0.25      # salience 高 임계 (≈ 14일 5건 언급)
SAL_WINDOW_DAYS = 14
SAL_SATURATION = 20  # 이 언급 수에서 salience 1.0


def conviction(independent: int, refute: int, source_types: int,
               pace_layer: str, status: str) -> float:
    """근거 강도 0~1 — 독립 관측 + 소스 다양성 + 느린 층 − 반박. contested는 감점."""
    base = min(independent, 3) / 3.0                      # 독립 관측 (최대 0.7 기여)
    base = base * 0.7
    base += min(source_types, 3) / 3.0 * 0.15            # 소스 유형 다양성 (A-3)
    base += _LAYER_W.get(pace_layer, 0.3) * 0.15         # 느린 층 가중 (A-5)
    if status == "corroborated":
        base += 0.1
    base -= min(refute, 3) / 3.0 * 0.35                  # 반박 감점 (ACH)
    if status == "contested":
        base -= 0.15
    return max(0.0, min(1.0, round(base, 3)))


def salience(conn, entity_ids: list[int], days: int = SAL_WINDOW_DAYS) -> float:
    """시장 주목 0~1 — 지식 주체 엔티티의 최근 창 언급 문서 수 (포화 정규화)."""
    if not entity_ids:
        return 0.0
    ph = ",".join("?" * len(entity_ids))
    n = conn.execute(
        f"""SELECT COUNT(DISTINCT el.doc_id) FROM entity_links el
            JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.entity_id IN ({ph})
              AND rd.published_at >= datetime('now', '-{days} days')""",
        entity_ids).fetchone()[0]
    return min(1.0, round(n / SAL_SATURATION, 3))


def quadrant(sal: float, conv: float) -> str:
    hi_s, hi_c = sal >= SAL_HIGH, conv >= CONV_HIGH
    if hi_s and hi_c:
        return "priced_in"
    if hi_s and not hi_c:
        return "overhyped"
    if not hi_s and hi_c:
        return "hidden_edge"
    return "noise"


def compute_state(conn, knowledge_id: int, independent: int, refute: int,
                  source_types: int, pace_layer: str, status: str) -> dict:
    """한 지식의 (salience, conviction, quadrant) — 라우터 items에서 항목별 호출."""
    ent_ids = [r[0] for r in conn.execute(
        "SELECT entity_id FROM knowledge_entities WHERE knowledge_id=?", (knowledge_id,))]
    sal = salience(conn, ent_ids)
    conv = conviction(independent, refute, source_types, pace_layer, status)
    return {"salience": sal, "conviction": conv, "quadrant": quadrant(sal, conv)}

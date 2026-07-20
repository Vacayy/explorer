"""이미 승인(actioned)된 contested_edge 제안 중 both_temporal 판정을 엣지에 소급 물질화(D-029).

feedback_note 컬럼 신설 이전에 승인된 both_temporal 제안은 result_json에만 근거가 갇혀 있었다.
그 판정을 해당 두 엣지의 feedback_note로 옮겨, contested 계산이 이 쌍을 제외하게 한다.
엣지 id는 내러티브 재계산으로 바뀌었을 수 있어 노드 이름(양방향 CAUSES)으로 매칭한다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection  # noqa: E402


def main() -> None:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, payload_json, result_json FROM agent_proposals "
        "WHERE kind='contested_edge' AND status='actioned'").fetchall()
    total = 0
    for r in rows:
        result = json.loads(r["result_json"] or "{}")
        if result.get("verdict") != "both_temporal":
            continue
        payload = json.loads(r["payload_json"] or "{}")
        a, b = payload.get("node_a"), payload.get("node_b")
        note = result.get("rationale") or "opus 판정: 시점 다른 피드백 나선(both_temporal)"
        cur = conn.execute("""
            UPDATE entity_relations SET feedback_note=?
            WHERE rel_type='CAUSES' AND id IN (
                SELECT er.id FROM entity_relations er
                JOIN entities s ON s.id=er.src_id JOIN entities d ON d.id=er.dst_id
                WHERE (s.name=? AND d.name=?) OR (s.name=? AND d.name=?))
        """, (note, a, b, b, a))
        if cur.rowcount:
            total += cur.rowcount
            print(f"  #{r['id']} {a} ↔ {b}: 엣지 {cur.rowcount}개 물질화")
        else:
            print(f"  #{r['id']} {a} ↔ {b}: 매칭 엣지 없음(재계산으로 소멸)")
    conn.commit()
    conn.close()
    print(f"완료 — feedback_note 물질화 엣지 {total}개")


if __name__ == "__main__":
    main()

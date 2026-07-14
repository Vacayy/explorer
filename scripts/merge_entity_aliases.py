"""표기 파편화 병합 (1회성) — 같은 기업의 한/영·대소문자 변형을 정본으로 통합.

enrich(haiku)가 영어 문서에서 'Meta'·'OpenAI'를 영문 그대로 뽑아 한국어
시딩 엔티티와 별개로 쪼갠 것을 정리. 정본 = 그룹 내 문서 링크가 가장 많은
표기. 변형의 entity_links·knowledge_entities·follows를 정본으로 이관하고
변형은 status='merged'로 (삭제 대신 — 참조 안전).

사용법: python scripts/merge_entity_aliases.py [--dry]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db

# 같은 기업의 표기 변형 그룹 (aliases 없는 해외/비상장 company만 대상)
GROUPS = [
    ["메타", "Meta"], ["애플", "Apple"], ["구글", "Google"], ["아마존", "Amazon"],
    ["마이크로소프트", "Microsoft", "MS", "마소"], ["테슬라", "Tesla"],
    ["엔비디아", "NVIDIA", "Nvidia"], ["오픈AI", "OpenAI", "오픈에이아이", "Open AI"],
    ["앤트로픽", "Anthropic"], ["스페이스X", "SpaceX", "스페이스엑스"],
    ["마이크론", "Micron"], ["브로드컴", "Broadcom"], ["TSMC", "티에스엠씨"],
    ["AMD", "에이엠디"], ["ASML", "에이에스엠엘"], ["오라클", "Oracle"],
    ["팔란티어", "Palantir"], ["데이터브릭스", "Databricks"],
]


def main(dry: bool):
    init_db()
    conn = get_connection()
    merged = 0
    for group in GROUPS:
        # 그룹의 실재 엔티티 (aliases 없는 company) + 문서 링크 수
        ents = []
        for name in group:
            r = conn.execute("""
                SELECT e.id, e.name, count(el.doc_id) n FROM entities e
                LEFT JOIN entity_links el ON el.entity_id=e.id
                WHERE e.type='company' AND e.name=? AND e.aliases IS NULL AND e.status IS NOT 'merged'
                GROUP BY e.id""", (name,)).fetchone()
            if r:
                ents.append(dict(r))
        if len(ents) < 2:
            continue
        ents.sort(key=lambda x: -x["n"])
        canon = ents[0]
        variants = ents[1:]
        print(f"  [{canon['name']}]({canon['n']}) ← " +
              ", ".join(f"{v['name']}({v['n']})" for v in variants))
        if dry:
            continue
        for v in variants:
            # 링크·지식·팔로우를 정본으로 이관 (중복은 무시)
            conn.execute("UPDATE OR IGNORE entity_links SET entity_id=? WHERE entity_id=?", (canon["id"], v["id"]))
            conn.execute("DELETE FROM entity_links WHERE entity_id=?", (v["id"],))
            conn.execute("UPDATE OR IGNORE knowledge_entities SET entity_id=? WHERE entity_id=?", (canon["id"], v["id"]))
            conn.execute("DELETE FROM knowledge_entities WHERE entity_id=?", (v["id"],))
            conn.execute("UPDATE OR IGNORE follows SET entity_id=? WHERE entity_id=?", (canon["id"], v["id"]))
            conn.execute("DELETE FROM follows WHERE entity_id=?", (v["id"],))
            conn.execute("UPDATE entities SET status='merged' WHERE id=?", (v["id"],))
            merged += 1
    conn.commit()
    conn.close()
    print(f"[merge] 변형 {merged}개 → 정본으로 병합" + (" (dry)" if dry else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    main(ap.parse_args().dry)

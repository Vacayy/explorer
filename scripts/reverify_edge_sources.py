"""D-204 재검증: 살아 있는 내러티브의 이전 방식(legacy_unverified) 엣지 근거를 현재 문서에서 다시 찾는다.

내러티브당 haiku 1콜 + 호스트 인용 확인. 기본은 대상 집계만(dry-run), --apply로 실행, --limit N으로 개수 제한.
확인 못 한 엣지는 그대로 둔다. 다음 내러티브 재생성 때도 같은 규칙으로 채워진다(_persist_causal).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection  # noqa: E402
from pipeline.narrative import reverify_legacy_edges  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = get_connection()
    targets = [r["id"] for r in conn.execute("""SELECT n.id, COUNT(DISTINCT er.id) k FROM narratives n
        JOIN narrative_edge_evidence nee ON nee.narrative_id=n.id JOIN entity_relations er ON er.id=nee.entity_relation_id
        WHERE n.superseded_at IS NULL AND COALESCE(n.kind,'topic')='topic' AND er.source_status='legacy_unverified'
        GROUP BY n.id ORDER BY k DESC""")]
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상 내러티브 {len(targets)}개")
    if not args.apply:
        print("dry-run(--apply로 실행)"); return
    checked = verified = 0
    cost = 0.0
    for nid in targets:
        try:
            out = reverify_legacy_edges(conn, nid)
        except Exception as exc:  # noqa: BLE001 — 한 내러티브 실패가 나머지를 막지 않는다
            print(f"  {nid}: 실패 {type(exc).__name__}: {str(exc)[:120]}"); continue
        checked += out["checked"]; verified += out["verified"]; cost += out.get("cost_usd") or 0
        print(f"  {nid}: {out['verified']}/{out['checked']} 확인 ({out['status']})", flush=True)
    print(f"합계 {verified}/{checked} 확인 · 비용 ${cost:.3f}")
    conn.close()


if __name__ == "__main__":
    main()

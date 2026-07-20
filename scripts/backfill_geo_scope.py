"""geo_scope 백필 (D-034) — 기존 인과 엣지에 장소 스코프를 소급 추론.

기본 = dry-run: geo_scope IS NULL인 CAUSES/BENEFITS_FROM 엣지의 (from, to, mechanism)을
haiku 배치로 통제어휘(GEO_VOCAB) 중 판정 → 계획을 사람이 검토 가능한 목록으로 출력하고
JSON으로 저장. --apply는 저장된 계획의 non-null 판정만 UPDATE (LLM 재호출 없음).

승인 모델(D-020 "기계는 제안, 사람은 승인"): dry-run으로 계획을 검토한 뒤에만 --apply.
판정이 애매하면 null 유지 — 억지 지정 금지(거짓 정밀 방지, geo-scope.md).

사용법:
  python scripts/backfill_geo_scope.py                # dry-run (계획 생성·저장)
  python scripts/backfill_geo_scope.py --apply        # 저장된 계획의 non-null만 적용
  python scripts/backfill_geo_scope.py --limit 200
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
from pipeline.narrative import GEO_VOCAB, _norm_geo

DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "logs" / "geo_backfill_plan.json"
BATCH = 18            # 콜당 엣지 수 (15~20)
MODEL = "haiku"       # 값싼 티어 — 짧은 판정


def _candidates(conn, limit: int) -> list[dict]:
    """geo_scope 미상 인과 엣지 — (from, to, mechanism)만 판정에 쓴다."""
    return [dict(r) for r in conn.execute("""
        SELECT er.id, s.name AS frm, d.name AS too, er.mechanism, er.rel_type
        FROM entity_relations er
        JOIN entities s ON s.id = er.src_id
        JOIN entities d ON d.id = er.dst_id
        WHERE er.geo_scope IS NULL AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
        ORDER BY er.id LIMIT ?""", (limit,)).fetchall()]


def _build_batch_prompt(batch: list[dict]) -> str:
    lines = "\n".join(
        f"{i}. {e['frm']} → {e['too']}" + (f" ({e['mechanism']})" if e.get("mechanism") else "")
        for i, e in enumerate(batch))
    return (
        "너는 투자 인과 주장의 '장소 스코프'를 판정한다. 아래 각 인과 고리(원인 → 결과)가 "
        "'어느 지역에서 성립하는 주장인지'를 통제어휘 중 하나로 고르되, 애매하면 null(억지 지정 금지).\n"
        f"통제어휘: {GEO_VOCAB}\n"
        "- 특정 지역 사건/정책/시장이면 해당국(한국·미국·중국·유럽·일본·대만).\n"
        "- 전세계 공통 동인(예: AI CAPEX 사이클, 글로벌 금리)이면 '글로벌'.\n"
        "- 목록 밖 특정 지역(예: 인도·중동)이면 '기타'. 판단 근거가 약하면 null.\n"
        'JSON만 출력: {"assignments": [{"i": 정수 인덱스, "geo": "어휘 중 하나 또는 null"}]}\n'
        f"[인과 고리 {len(batch)}개]\n{lines}"
    )


def _judge_batch(batch: list[dict]) -> dict[int, str]:
    """배치 → {entity_relation_id: geo}. null·어휘 밖은 제외(빠지면 null 유지)."""
    raw = _call_claude_code(_build_batch_prompt(batch), model=MODEL, timeout=180)
    data = _parse_json(raw)
    out: dict[int, str] = {}
    for a in (data.get("assignments") or []):
        try:
            idx = int(a.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(batch):
            geo = _norm_geo(a.get("geo"))
            if geo:
                out[batch[idx]["id"]] = geo
    return out


def run_dry(limit: int, plan_path: Path) -> None:
    conn = get_connection()
    candidates = _candidates(conn, limit)
    print(f"[후보] geo_scope IS NULL 인과 엣지 {len(candidates)}개 (limit={limit})")
    if not candidates:
        conn.close()
        return
    if llm_engine() != "claude-code":
        print("판정 불가 — .env ENRICH_ENGINE=claude-code 필요. 후보만 세고 종료.")
        conn.close()
        return

    by_id = {e["id"]: e for e in candidates}
    assigned: dict[int, str] = {}
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i + BATCH]
        try:
            assigned.update(_judge_batch(batch))
        except Exception as ex:  # noqa: BLE001 — 배치 하나 실패가 전체를 막지 않게
            print(f"  배치 {i // BATCH} 판정 실패: {str(ex)[:120]}")

    dist: dict[str, int] = {}
    for geo in assigned.values():
        dist[geo] = dist.get(geo, 0) + 1
    null_n = len(candidates) - len(assigned)

    print(f"\n[판정] 지정 {len(assigned)}개 / null 유지 {null_n}개")
    print("[분포] " + " · ".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda x: -x[1]))
          + f" · null {null_n}")
    print("\n=== 대표 예시 (최대 5개) ===")
    for rid, geo in list(assigned.items())[:5]:
        e = by_id[rid]
        print(f"  [{geo}] {e['frm']} → {e['too']}"
              + (f"  ({e['mechanism'][:60]})" if e.get("mechanism") else ""))

    plan = {"limit": limit,
            "plan": [{"id": rid, "geo": geo, "frm": by_id[rid]["frm"], "too": by_id[rid]["too"]}
                     for rid, geo in assigned.items()]}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[계획 저장] {plan_path}  (검토 후 --apply 로 {len(assigned)}개 적용)")
    conn.close()


def run_apply(plan_path: Path) -> None:
    if not plan_path.exists():
        print(f"계획 파일 없음: {plan_path} — 먼저 dry-run 실행")
        sys.exit(1)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    items = plan.get("plan") or []
    if not items:
        print("계획에 적용할 판정이 없음.")
        return
    conn = get_connection()
    applied = 0
    for it in items:
        geo = _norm_geo(it.get("geo"))
        if not geo:
            continue
        cur = conn.execute(
            "UPDATE entity_relations SET geo_scope=? WHERE id=? AND geo_scope IS NULL",
            (geo, it["id"]))
        applied += cur.rowcount
    conn.commit()
    conn.close()
    print(f"[적용 완료] {applied}개 엣지에 geo_scope 기록")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="저장된 계획의 non-null 판정 적용 (기본=dry-run)")
    ap.add_argument("--limit", type=int, default=500, help="판정 후보 상한")
    ap.add_argument("--plan", type=str, default=str(DEFAULT_PLAN))
    args = ap.parse_args()

    init_db()
    plan_path = Path(args.plan)
    if args.apply:
        run_apply(plan_path)
    else:
        run_dry(args.limit, plan_path)


if __name__ == "__main__":
    main()
